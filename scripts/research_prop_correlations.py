"""Same-game prop correlations for the parlay generator.

Books price same-game parlays with correlation models (FanDuel since 2019);
multiplying leg prices ignores it. This measures how two player stats move
together in the same NFL game, by relationship:

- same player (e.g. a receiver's receptions and receiving yards);
- teammates (a QB's passing yards and his receivers' receiving yards);
- opponents (both offenses in a shootout).

Each stat is first centred on the player's own mean for that season (so the
correlation is about the game, not about good players), then the Spearman
rank correlation of the residuals is taken per (relationship, position:stat,
position:stat) over 2023-2025 regular seasons, shrunk toward 0 by n/(n+200)
and kept when n >= 150. 2026 games (through the cutoff) are held out and the
Gaussian-copula joint hit rate is compared with independence on them.

Run in the worker environment: python -m scripts.research_prop_correlations
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import multivariate_normal, norm, spearmanr

from src.db.client import get_worker_db
from src.services.projection_engine import load_history

OUT = Path(__file__).resolve().parents[1] / "config" / "prop_correlations.json"
STATS = ("passing_yards", "passing_attempts", "passing_completions", "passing_touchdowns", "passing_interceptions",
         "rushing_yards", "rushing_attempts", "receptions", "receiving_yards")
POSITIONS = ("QB", "RB", "WR", "TE")
TRAIN = (2023, 2024, 2025)
TEST = 2026
MIN_N = 150
SHRINK = 200


def residuals(history, seasons):
    """{(game, team, player, position): {stat: residual}} for qualifying player-games."""
    by_player_season = defaultdict(list)
    for p in history.players.values():
        g = history.games[p.game_id]
        pos = history.positions.get(p.player_id)
        if g.season in seasons and pos in POSITIONS:
            by_player_season[(p.player_id, g.season)].append(p)
    out = {}
    for games in by_player_season.values():
        if len(games) < 4:
            continue
        means = {s: np.mean([gm.stats.get(s, 0.0) for gm in games]) for s in STATS}
        pos = history.positions[games[0].player_id]
        for gm in games:
            out[(gm.game_id, gm.team_id, gm.player_id, pos)] = {s: gm.stats.get(s, 0.0) - means[s] for s in STATS if means[s] > 0}
    return out


def pairs(res):
    """{(relation, 'POS:stat', 'POS:stat'): ([x], [y])} with keys ordered so each pair is counted once."""
    by_game = defaultdict(list)
    for (game, team, player, pos), stats in res.items():
        by_game[game].append((team, player, pos, stats))
    acc = defaultdict(lambda: ([], []))
    for players in by_game.values():
        for team, player, pos, stats in players:
            for a, b in combinations(sorted(stats), 2):
                k = ("same_player", f"{pos}:{a}", f"{pos}:{b}")
                acc[k][0].append(stats[a])
                acc[k][1].append(stats[b])
        for (t1, p1, pos1, s1), (t2, p2, pos2, s2) in combinations(players, 2):
            relation = "teammate" if t1 == t2 else "opponent"
            for a in s1:
                for b in s2:
                    x, y = (f"{pos1}:{a}", s1[a]), (f"{pos2}:{b}", s2[b])
                    if x[0] > y[0]:
                        x, y = y, x
                    k = (relation, x[0], y[0])
                    acc[k][0].append(x[1])
                    acc[k][1].append(y[1])
    return acc


def fit(acc):
    table = {}
    for (relation, a, b), (x, y) in acc.items():
        n = len(x)
        if n < MIN_N:
            continue
        rho = spearmanr(x, y).statistic
        if np.isfinite(rho):
            table[f"{relation}|{a}|{b}"] = {"rho": round(float(rho * n / (n + SHRINK)), 3), "n": n}
    return table


def marginals(res):
    """P(residual > 0) per 'POS:stat' (stats are skewed, so this is not 0.5)."""
    counts = defaultdict(lambda: [0, 0])
    for (_, _, _, pos), stats in res.items():
        for s, v in stats.items():
            counts[f"{pos}:{s}"][0] += v > 0
            counts[f"{pos}:{s}"][1] += 1
    return {k: a / b for k, (a, b) in counts.items() if b}


def joint(p1, p2, rho):
    """P(both) for two events with marginals p1, p2 under a Gaussian copula with latent correlation rho."""
    t1, t2 = norm.ppf(1 - p1), norm.ppf(1 - p2)
    # P(Z1 > t1, Z2 > t2) = P(-Z1 < -t1, -Z2 < -t2), same correlation.
    return float(multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([-t1, -t2]))


def holdout(table, res_test, margins):
    """Two-leg 'both above the player's own season mean' events: copula vs independence (Brier on the pair outcome).

    Reported for every pair with a fitted correlation and for the |rho| >= 0.15 subset, where it matters.
    """
    by_game = defaultdict(list)
    for (game, team, player, pos), stats in res_test.items():
        by_game[game].append((team, pos, stats))
    errors = defaultdict(list)

    def score(relation, x, vx, y, vy):
        key = f"{relation}|{min(x, y)}|{max(x, y)}"
        p1, p2 = margins.get(x), margins.get(y)
        if key not in table or p1 is None or p2 is None:
            return
        rho = table[key]["rho"]
        both = float(vx > 0 and vy > 0)
        c, i = (joint(p1, p2, rho) - both) ** 2, (p1 * p2 - both) ** 2
        for group in ("all", "strong") if abs(rho) >= 0.15 else ("all",):
            errors[(group, "copula")].append(c)
            errors[(group, "independent")].append(i)

    for players in by_game.values():
        for team, pos, stats in players:
            for a, b in combinations(sorted(stats), 2):
                score("same_player", f"{pos}:{a}", stats[a], f"{pos}:{b}", stats[b])
        for (t1, pos1, s1), (t2, pos2, s2) in combinations(players, 2):
            relation = "teammate" if t1 == t2 else "opponent"
            for a in s1:
                for b in s2:
                    score(relation, f"{pos1}:{a}", s1[a], f"{pos2}:{b}", s2[b])
    out = defaultdict(dict)
    for (group, model), v in errors.items():
        out[group][model] = {"n": len(v), "brier": round(float(np.mean(v)), 5)}
    return dict(out)


async def main():
    now = datetime.now(timezone.utc)
    async with get_worker_db() as db:
        history = await load_history(db, list(TRAIN) + [TEST], now)
    train_res = residuals(history, set(TRAIN))
    train, margins = fit(pairs(train_res)), marginals(train_res)
    test = residuals(history, {TEST})
    # Holdout uses a sample of games to keep the bivariate CDF calls bounded.
    games = sorted({k[0] for k in test})[:120]
    sample = {k: v for k, v in test.items() if k[0] in set(games)}
    evaluation = holdout(train, sample, margins)
    strongest = sorted(train.items(), key=lambda kv: -abs(kv[1]["rho"]))[:15]
    payload = {"version": "spearman_residual_v1", "train_seasons": list(TRAIN), "min_n": MIN_N, "shrink": SHRINK,
               "generated_at": now.isoformat(), "holdout": {"season": TEST, "games": len(games), **evaluation},
               "pairs": dict(sorted(train.items()))}
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(json.dumps({"pairs": len(train), "holdout": payload["holdout"], "strongest": strongest}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
