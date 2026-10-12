"""Player props: engine projection + fitted spread vs the history baseline and the market.

Prop tools (Outlier, BettingPros' prop analyzer, Unabated's prop tools)
price a prop from a projection of the stat and its distribution, then compare
to the de-vigged market. This experiment:

- engine: projection engine v1 walk-forward mean for the stat; spread fitted on
  2025 engine residuals only (sd = c * mean ** 0.5 for yards; Poisson for
  receptions), then frozen for 2026;
- history: the serving baseline (mean/sd of the player's prior games, normal);
- market: multiplicative no-vig probability from the same quote;
- regressed: market + w * (engine - market) on the log-odds scale, w fitted on
  the first half of 2026 weeks and scored on the second half.

Each prop is the latest pregame quote with both prices per (player, game,
stat, source); graded only when the player recorded the stat's game.
Run in the worker environment: python -m scripts.research_prop_model
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm, poisson
from sqlalchemy import select

from src.db.client import get_worker_db
from src.models.facts import Game, PlayerPropLine
from src.services.projection_engine import DEFAULT, compute, load_history
from src.utils.odds_math import american_to_implied
from scripts.tune_projection_engine import week_slates

STATS = {"receptions": "count", "receiving_yards": "yards", "rushing_yards": "yards"}


def p_over(kind, mean, line, c):
    if mean <= 0:
        return 0.0
    if kind == "count":
        return float(1 - poisson.cdf(math.floor(line), mean))
    return float(1 - norm.cdf((line - mean) / max(1.0, c * math.sqrt(mean))))


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def score(probs, outcomes):
    p = np.clip(np.array(probs), 1e-4, 1 - 1e-4)
    y = np.array(outcomes, float)
    return {"n": len(y), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)}


async def main():
    async with get_worker_db() as db:
        history = await load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
        quotes = (await db.execute(select(PlayerPropLine, Game).join(Game, Game.id == PlayerPropLine.game_id).where(
            Game.sport == "nfl", Game.season == 2026, Game.status == "final", PlayerPropLine.stat_type.in_(list(STATS)),
            PlayerPropLine.over_price_american.is_not(None), PlayerPropLine.under_price_american.is_not(None)))).all()
    slates = week_slates(history)
    engine = {}  # (player, game) -> stats
    for (season, week), (cutoff, targets, _) in slates.items():
        if season < 2025:
            continue
        for pid, proj in compute(history, targets, cutoff, DEFAULT).items():
            engine[(pid, proj.game_id)] = (season, week, proj.stats)
    # Spread for yards from 2025 residuals: sd = c * sqrt(mean).
    c = {}
    for stat, kind in STATS.items():
        if kind != "yards":
            continue
        ratios = []
        for (pid, gid), (season, _, stats) in engine.items():
            played = history.players.get((pid, gid))
            if season == 2025 and played and stats.get(stat, 0) > 5:
                ratios.append((played.stats.get(stat, 0.0) - stats[stat]) / math.sqrt(stats[stat]))
        c[stat] = float(np.std(ratios))
    # Empirical alternative: 2025 actual/projected ratios by projection tercile.
    ratios = {}
    for stat in STATS:
        pairs = [(stats.get(stat, 0.0), history.players[(pid, gid)].stats.get(stat, 0.0))
                 for (pid, gid), (season, _, stats) in engine.items()
                 if season == 2025 and (pid, gid) in history.players and stats.get(stat, 0.0) > 0.5]
        means = np.array([m for m, _ in pairs])
        edges = np.quantile(means, [1 / 3, 2 / 3])
        ratios[stat] = (edges, [np.array([a / m for m, a in pairs if b(m)]) for b in (
            lambda m: m < edges[0], lambda m: edges[0] <= m < edges[1], lambda m: m >= edges[1])])

    def empirical(stat, mean, line):
        if mean <= 0:
            return 0.0
        edges, buckets = ratios[stat]
        r = buckets[0 if mean < edges[0] else 1 if mean < edges[1] else 2]
        return float(np.mean(r * mean > line))

    latest = {}
    for q, g in quotes:
        if q.observed_at >= g.game_time:
            continue
        key = (q.player_id, q.game_id, q.stat_type, q.source)
        if key not in latest or q.observed_at > latest[key][0].observed_at:
            latest[key] = (q, g)
    by_player = defaultdict(list)
    for p in history.players.values():
        by_player[p.player_id].append(p)
    rows = defaultdict(list)
    for (pid, gid, stat, _), (q, g) in latest.items():
        played = history.players.get((pid, gid))
        e = engine.get((pid, gid))
        if played is None or e is None or q.line.is_integer():
            continue
        actual = played.stats.get(stat, 0.0)
        over_i, under_i = american_to_implied(q.over_price_american), american_to_implied(q.under_price_american)
        market = over_i / (over_i + under_i)
        prior = [p.stats.get(stat, 0.0) for p in by_player[pid] if p.kickoff < g.game_time]
        hist = None
        if len(prior) >= 4:
            sd = float(np.std(prior, ddof=1)) or 1.0
            hist = float(1 - norm.cdf((q.line - np.mean(prior)) / sd))
        rows[stat].append({"week": e[1], "y": float(actual > q.line), "market": market, "history": hist,
                           "engine": p_over(STATS[stat], e[2].get(stat, 0.0), q.line, c.get(stat, 1.0)),
                           "empirical": empirical(stat, e[2].get(stat, 0.0), q.line)})
    report = {"yards_sd_scale_fit_2025": {k: round(v, 3) for k, v in c.items()}, "stats": {}}
    for stat, rs in rows.items():
        weeks = sorted({r["week"] for r in rs})
        half = weeks[len(weeks) // 2]
        fit, test = [r for r in rs if r["week"] < half], [r for r in rs if r["week"] >= half]
        best = min(np.arange(0, 1.01, 0.05), key=lambda w: score(
            [1 / (1 + math.exp(-(logit(r["market"]) + w * (logit(r["engine"]) - logit(r["market"]))))) for r in fit],
            [r["y"] for r in fit])["log_loss"])
        reg = lambda r: 1 / (1 + math.exp(-(logit(r["market"]) + best * (logit(r["engine"]) - logit(r["market"])))))
        with_hist = [r for r in test if r["history"] is not None]
        report["stats"][stat] = {
            "test_weeks": [half, weeks[-1]], "regression_weight_fit_on_earlier_weeks": round(float(best), 2),
            "test": {"market": score([r["market"] for r in test], [r["y"] for r in test]),
                     "engine": score([r["engine"] for r in test], [r["y"] for r in test]),
                     "engine_empirical": score([r["empirical"] for r in test], [r["y"] for r in test]),
                     "all_weeks": {k: score([r[k] for r in rs], [r["y"] for r in rs]) for k in ("market", "engine", "empirical")},
                     "all_weeks_history_rows": {k: score([r[k] for r in rs if r["history"] is not None],
                                                         [r["y"] for r in rs if r["history"] is not None])
                                                for k in ("history", "empirical", "engine", "market")},
                     "regressed": score([reg(r) for r in test], [r["y"] for r in test]),
                     "history_subset": score([r["history"] for r in with_hist], [r["y"] for r in with_hist]),
                     "market_on_history_subset": score([r["market"] for r in with_hist], [r["y"] for r in with_hist])}}
    print(json.dumps(report, indent=1))
    if "--write-config" in __import__("sys").argv:
        # Serving artifact: 2025 actual/projected ratio quantiles per projection tercile.
        artifact = {"recipe": "prop_engine_ratio_v1", "fitted_on": "projection engine v1 walk-forward, 2025 weeks",
                    "stats": {stat: {"edges": [round(float(x), 4) for x in edges],
                                     "quantiles": [[round(float(q), 4) for q in np.quantile(b, np.linspace(0, 1, 201))]
                                                   for b in buckets]}
                              for stat, (edges, buckets) in ratios.items()},
                    "evidence": {stat: v["test"]["all_weeks_history_rows"] for stat, v in report["stats"].items()},
                    "note": "On the same 2026 props every model, including this one, was worse than the no-vig market."}
        json.dump(artifact, open("/app/out/prop_engine_distribution.json", "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main())
