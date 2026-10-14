"""Market-implied player projections (the BettingPros / WalterPicks "Vegas" method) vs each source.

Prop markets are the best single forecaster of a player's stat line we have
(docs/2026-10-12-engine-research.md: on 2026 props every model lost to the
no-vig market). This experiment turns each prop into a mean and swaps it into
the fantasy projections:

1. Market mean. For each (player, game, stat), the latest pregame two-sided
   quote per book (DFS pick'em excluded) -> the board's no-vig consensus at
   the main line (src/services/prop_board.consensus). The implied mean m
   solves P(X > line | m) = fair over, with X from the same distributions the
   prop engine uses (empirical actual/projection ratios fitted on 2025 for
   receptions, receiving and rushing yards); Poisson for TDs, interceptions
   and carries; normal with a 2025-fitted coefficient of variation for
   passing yards, attempts and completions.
2. Adjusted projection. Each source's stat line (Sleeper, ESPN, engine v1)
   with stat k moved toward the market: base + w_k (market - base). Receiving
   and rushing TDs scale with the market/base yards ratio raised to `td_power`.
   Weights are fitted leave-one-week-out (each week scored with weights fitted
   on the other weeks), so no week grades itself.
3. Scored with one Sleeper league's rules on the FantasyPros pool (top-N by
   Sleeper projection or by actual, per position) of rows every source covers.

Caveat: past-week Sleeper/ESPN projections are their final stored values, not
timestamped pregame captures. Prospective capture is what qualifies a model.
Run in the worker environment:
    python -m scripts.research_market_projection [--weeks 1-5] [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import numpy as np
from scipy.stats import norm, poisson
from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerPropLine
from src.models.sleeper import SleeperLeague
from src.services import prop_engine
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from src.services.prop_board import EXCLUDED_BOOKS, consensus
from src.services.projection_engine import DEFAULT, compute, load_history
from scripts.research_projection_consensus import espn_week, points, sleeper_week
from scripts.tune_projection_engine import POOL, week_slates

SEASON = 2026
# Prop stat -> Sleeper scoring key.
MARKET_KEYS = {"receptions": "rec", "receiving_yards": "rec_yd", "rushing_yards": "rush_yd",
               "passing_yards": "pass_yd", "passing_touchdowns": "pass_td", "passing_interceptions": "pass_int",
               "rushing_attempts": "rush_att", "passing_attempts": "pass_att", "passing_completions": "pass_cmp"}
POISSON = {"passing_touchdowns", "passing_interceptions", "rushing_attempts"}
NORMAL = {"passing_yards", "passing_attempts", "passing_completions"}
TD_LINKS = {"rec_td": "rec_yd", "rush_td": "rush_yd"}
INTERNAL_TO_SLEEPER = {v: k for k, v in CORE.items()}


FAMILY = {"value": "ratio"}  # "ratio": prop engine's empirical ratios; "normal": 2025-fitted CV for yards
VOLUME_GATE = {"passing_yards": ("passing_attempts", 15), "passing_attempts": ("passing_attempts", 15),
               "passing_completions": ("passing_attempts", 15), "receiving_yards": ("targets", 4),
               "rushing_yards": ("rushing_attempts", 8)}


def over_probability(stat: str, mean: float, line: float, cv: dict) -> float | None:
    if FAMILY["value"] == "normal" and stat in ("receiving_yards", "rushing_yards"):
        return float(1 - norm.cdf((line - mean) / max(1e-6, cv[stat] * mean)))
    if FAMILY["value"] == "normal" and stat == "receptions":
        return float(1 - poisson.cdf(math.floor(line), mean))
    if stat in prop_engine.STATS:
        return prop_engine.over_probability(stat, mean, line)
    if stat in POISSON:
        return float(1 - poisson.cdf(math.floor(line), mean))
    if stat in NORMAL:
        return float(1 - norm.cdf((line - mean) / max(1e-6, cv[stat] * mean)))
    return None


def implied_mean(stat: str, line: float, fair_over: float, cv: dict) -> float | None:
    """Bisection on the mean: P(over) is increasing in it for every family used here."""
    lo, hi = 1e-3, max(4.0 * line, line + 10.0)
    p_lo, p_hi = over_probability(stat, lo, line, cv), over_probability(stat, hi, line, cv)
    if p_lo is None or not p_lo <= fair_over <= p_hi:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if over_probability(stat, mid, line, cv) < fair_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fitted_cv(stats_2025: list[dict]) -> dict:
    """Within-player coefficient of variation per normal-family stat, from 2025 player-games only."""
    by_player = defaultdict(lambda: defaultdict(list))
    for row in stats_2025:
        for stat, (gate, minimum) in VOLUME_GATE.items():
            if row["stats"].get(gate, 0) >= minimum:
                by_player[row["player_id"]][stat].append(float(row["stats"].get(stat, 0.0)))
    out = {}
    for stat in VOLUME_GATE:
        ratios = [np.std(v, ddof=1) / np.mean(v) for p in by_player.values() if len(v := p[stat]) >= 6 and np.mean(v) > 0]
        out[stat] = round(float(np.median(ratios)), 4)
    return out


def adjust(base: dict, market: dict, w: dict, td_power: float) -> dict:
    out = dict(base)
    for key, value in market.items():
        out[key] = base.get(key, 0.0) + w.get(key, 1.0) * (value - base.get(key, 0.0))
    for td, yards in TD_LINKS.items():
        if yards in market and base.get(yards, 0) > 1 and td in base:
            out[td] = base[td] * (max(out[yards], 0.0) / base[yards]) ** td_power
    return out


async def market_means(db, cv) -> dict:
    """(player id, game id) -> {sleeper key: implied mean} from the latest pregame quote per book."""
    rows = (await db.execute(select(PlayerPropLine, Game.game_time).join(Game, Game.id == PlayerPropLine.game_id).where(
        Game.sport == "nfl", Game.season == SEASON, Game.status == "final", Game.game_time.is_not(None),
        PlayerPropLine.stat_type.in_(list(MARKET_KEYS)), PlayerPropLine.observed_at < Game.game_time,
        PlayerPropLine.over_price_american.is_not(None), PlayerPropLine.under_price_american.is_not(None)))).all()
    latest = {}
    for q, _ in rows:
        book = q.source.split("_", 1)[-1]
        if book in EXCLUDED_BOOKS:
            continue
        k = (q.player_id, q.game_id, q.stat_type, book)
        if k not in latest or q.observed_at > latest[k].observed_at:
            latest[k] = q
    offers = defaultdict(list)
    for (pid, gid, stat, book), q in latest.items():
        offers[(pid, gid, stat)].append({"book": book, "line": q.line, "over": q.over_price_american,
                                         "under": q.under_price_american,
                                         "observed_at": q.observed_at})
    out = defaultdict(dict)
    books = defaultdict(dict)
    for (pid, gid, stat), group in offers.items():
        c = consensus(group)
        if c.get("fair_over") is None:
            continue
        m = implied_mean(stat, c["line"], c["fair_over"], cv)
        if m is not None:
            out[(pid, gid)][MARKET_KEYS[stat]] = m
            books[(pid, gid)][MARKET_KEYS[stat]] = c["books"]
    return out, books


async def run(weeks, league_id, min_books):
    s = get_settings()
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await load_history(db, [2025, SEASON], datetime.now(timezone.utc))
        season_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        cv = fitted_cv([{"player_id": pg.player_id, "stats": pg.stats} for pg in history.players.values()
                        if pg.kickoff < season_start])
        market, market_books = await market_means(db, cv)
        espn_league = s.espn_league_ids.split(",")[0].strip()
        cookies = {"espn_s2": s.espn_s2, "SWID": s.espn_swid} if s.espn_s2 else None
        async with httpx.AsyncClient(base_url=s.espn_fantasy_base_url, cookies=cookies, timeout=60) as ec, \
                httpx.AsyncClient(timeout=60) as sc:
            espn = {w: await espn_week(ec, espn_league, w) for w in weeks}
            sleeper = {w: await sleeper_week(sc, w) for w in weeks}
        espn_ids = await resolve_platform_players(db, "espn", sorted({i for v in espn.values() for i in v}))
        sleeper_ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
    weights = offensive_weights(league.scoring_settings)
    internal = {CORE[k]: w for k, w in weights.items() if k in CORE}
    slates = week_slates(history)
    rows = []  # dicts: week, position, sources {name: stat dict}, market, actual points
    for w in weeks:
        if (SEASON, w) not in slates:
            continue
        cutoff, targets, actual = slates[(SEASON, w)]
        engine = compute(history, targets, cutoff, DEFAULT)
        e = {espn_ids[i].id: v for i, v in espn[w].items() if espn_ids.get(i)}
        sl = {sleeper_ids[i].id: v for i, v in sleeper[w].items() if sleeper_ids.get(i)}
        for pid, proj in engine.items():
            played = actual.get(pid)
            if played is None or played.game_id != proj.game_id or pid not in e or pid not in sl:
                continue
            mk = {k: v for k, v in market.get((pid, proj.game_id), {}).items()
                  if market_books[(pid, proj.game_id)][k] >= min_books}
            eng = {INTERNAL_TO_SLEEPER[k]: v for k, v in proj.stats.items() if k in INTERNAL_TO_SLEEPER}
            rows.append({"week": w, "position": proj.position, "market": mk,
                         "sources": {"sleeper": {k: float(v) for k, v in sl[pid].items() if isinstance(v, (int, float))},
                                     "espn": e[pid], "engine": eng},
                         "actual_stats": {INTERNAL_TO_SLEEPER[k]: v for k, v in played.stats.items() if k in INTERNAL_TO_SLEEPER},
                         "actual": sum(float(played.stats.get(k, 0.0)) * v for k, v in internal.items())})
    groups = defaultdict(list)
    for r in rows:
        r["sleeper_points"] = points(r["sources"]["sleeper"], weights)
        groups[(r["week"], r["position"])].append(r)
    pool = []
    for (w, pos), members in groups.items():
        n = POOL[pos]
        keep = {id(r) for r in sorted(members, key=lambda r: -r["sleeper_points"])[:n]} | \
               {id(r) for r in sorted(members, key=lambda r: -r["actual"])[:n]}
        pool += [r for r in members if id(r) in keep]
    y = np.array([r["actual"] for r in pool])
    wk = np.array([r["week"] for r in pool])
    has_market = np.array([bool(r["market"]) for r in pool])

    def predict(source, w, td_power):
        return np.array([points(adjust(r["sources"][source], r["market"], w, td_power), weights)
                         if r["market"] else points(r["sources"][source], weights) for r in pool])

    def mae(pred, mask):
        return round(float(np.mean(np.abs(pred[mask] - y[mask]))), 4) if mask.any() else None

    grid = [g for g in itertools.product((0.0, 0.25, 0.5, 0.75, 1.0), repeat=3)]
    groups_of_keys = (("rec", "rec_yd"), ("rush_yd", "rush_att"), ("pass_yd", "pass_td", "pass_int", "pass_att", "pass_cmp"))

    def w_of(g):
        return {k: g[i] for i, keys in enumerate(groups_of_keys) for k in keys}

    def lowo(source, base):
        """Leave-one-week-out: weights per stat group and TD power fitted on the other weeks."""
        cache = {(g, tp): predict(source, w_of(g), tp) for g in grid for tp in (0.0, 0.5, 1.0)}
        pred = base.copy()
        chosen = {}
        for w in sorted(set(wk)):
            train, test = (wk != w) & has_market, wk == w
            best = min(cache, key=lambda key: (np.mean(np.abs(cache[key][train] - y[train])), -sum(key[0]), key[1]))
            pred[test] = cache[best][test]
            chosen[int(w)] = {"weights": dict(zip(("receiving", "rushing", "passing"), best[0])), "td_power": best[1]}
        return pred, chosen

    report = {"season": SEASON, "weeks": weeks, "family": FAMILY["value"], "league_id": league.league_id, "min_books": min_books, "cv": cv,
              "pool_rows": int(len(y)), "rows_with_market": int(has_market.sum()),
              "market_stats": dict(sorted(defaultdict(int, {k: sum(k in r["market"] for r in pool) for k in MARKET_KEYS.values()}).items()))}
    results, by_week, chosen_all = {}, {}, {}
    base = {name: np.array([points(r["sources"][name], weights) for r in pool]) for name in ("sleeper", "espn", "engine")}
    base["consensus"] = (base["sleeper"] + base["espn"] + base["engine"]) / 3
    preds = dict(base)
    for name in ("sleeper", "espn", "engine"):
        preds[f"{name}+market_full"] = predict(name, w_of((1.0, 1.0, 1.0)), 1.0)
        preds[f"{name}+market_lowo"], chosen_all[name] = lowo(name, base[name])
    preds["consensus+market_lowo"] = (preds["sleeper+market_lowo"] + preds["espn+market_lowo"] + preds["engine+market_lowo"]) / 3
    preds["consensus+market_full"] = (preds["sleeper+market_full"] + preds["espn+market_full"] + preds["engine+market_full"]) / 3
    everyone = np.ones(len(y), bool)
    for name, p in preds.items():
        results[name] = {"pool": mae(p, everyone), "with_market": mae(p, has_market)}
        by_week[name] = {int(w): mae(p, (wk == w) & has_market) for w in sorted(set(wk))}
    # Paired bootstrap of the market adjustment on the rows it touches (Sleeper and consensus bases).
    rng = np.random.default_rng(7)
    idx = np.flatnonzero(has_market)
    paired = {}
    for a, b in (("sleeper+market_lowo", "sleeper"), ("consensus+market_lowo", "consensus"), ("consensus+market_lowo", "sleeper")):
        diff = np.abs(preds[a][idx] - y[idx]) - np.abs(preds[b][idx] - y[idx])
        boots = [float(np.mean(diff[rng.integers(0, len(diff), len(diff))])) for _ in range(4000)]
        paired[f"{a} - {b}"] = {"mean": round(float(diff.mean()), 4), "ci95": [round(float(np.percentile(boots, 2.5)), 4),
                                                                              round(float(np.percentile(boots, 97.5)), 4)]}
    # Stat level: does the market mean beat each source on the stat itself, and is it biased?
    stat_level = {}
    for key in MARKET_KEYS.values():
        rs = [r for r in pool if key in r["market"] and key in r["actual_stats"]]
        if len(rs) < 15:
            continue
        a = np.array([r["actual_stats"][key] for r in rs])
        entry = {"n": len(rs), "market_mae": round(float(np.mean(np.abs(np.array([r["market"][key] for r in rs]) - a))), 3),
                 "market_bias": round(float(np.mean(np.array([r["market"][key] for r in rs]) - a)), 3)}
        for name in ("sleeper", "espn", "engine"):
            b = np.array([float(r["sources"][name].get(key, 0.0)) for r in rs])
            entry[f"{name}_mae"] = round(float(np.mean(np.abs(b - a))), 3)
            entry[f"{name}_bias"] = round(float(np.mean(b - a)), 3)
        stat_level[key] = entry
    report["stat_level"] = stat_level
    report.update({"mae": results, "by_week_with_market": by_week, "paired_with_market": paired, "lowo_choices": chosen_all})
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default="1-5")
    ap.add_argument("--league")
    ap.add_argument("--min-books", type=int, default=2)
    ap.add_argument("--family", choices=("ratio", "normal"), default="ratio")
    a = ap.parse_args()
    FAMILY["value"] = a.family
    lo, hi = map(int, a.weeks.split("-"))
    print(json.dumps(asyncio.run(run(list(range(lo, hi + 1)), a.league, a.min_books)), indent=1, default=str))


if __name__ == "__main__":
    main()
