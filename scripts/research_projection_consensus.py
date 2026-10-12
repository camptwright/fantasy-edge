"""Consensus projections (the FantasyPros method) vs each single source.

Sources for each completed 2026 week, all re-scored with one Sleeper
league's rules so they are compared like for like:
- Sleeper (licensed from RotoWire): the public weekly projections endpoint.
- ESPN: stat-level projections (statSourceId 1) from kona_player_info.
- Projection engine v1: walk-forward compute from games before the week.

Pool: FantasyPros in-season pool (top-N by Sleeper projection or by actual,
per position) restricted to players with all three projections, so every
source is graded on the same rows. Consensus weights are fitted
leave-one-week-out (each week scored with weights from the other weeks).

Caveat: Sleeper's and ESPN's past-week projections are their final stored
values, not timestamped pregame captures; the prospective archives are what
qualify a model. Run in the worker environment:
    python -m scripts.research_projection_consensus [--weeks 1-5] [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import numpy as np
from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from src.services.projection_engine import DEFAULT, compute, load_history, score
from scripts.tune_projection_engine import POOL, week_slates

SEASON = 2026
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
# ESPN projected stat ids -> Sleeper scoring keys (61 duplicates 42 and is ignored).
ESPN_KEYS = {"3": "pass_yd", "4": "pass_td", "19": "pass_2pt", "20": "pass_int", "24": "rush_yd", "25": "rush_td",
             "26": "rush_2pt", "53": "rec", "42": "rec_yd", "43": "rec_td", "44": "rec_2pt", "72": "fum_lost"}


async def espn_week(client, league_id, week, limit=1000):
    f = {"players": {"limit": limit, "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                     "filterSlotIds": {"value": [0, 2, 4, 6]}}}
    r = await client.get(f"/seasons/{SEASON}/segments/0/leagues/{league_id}",
                         params={"view": "kona_player_info", "scoringPeriodId": week},
                         headers={"x-fantasy-filter": json.dumps(f)})
    r.raise_for_status()
    out = {}
    for item in r.json().get("players", []):
        p = item.get("player", {})
        if p.get("defaultPositionId") not in POSITIONS:
            continue
        proj = next((x for x in p.get("stats", []) if x.get("statSourceId") == 1 and x.get("scoringPeriodId") == week), None)
        if proj and proj.get("stats"):
            out[str(p["id"])] = {k: float(proj["stats"][i]) for i, k in ESPN_KEYS.items() if i in proj["stats"]}
    return out


async def sleeper_week(client, week):
    """The same endpoint the Sleeper ingest uses: an id-keyed object of flat stat dicts."""
    r = await client.get(f"{get_settings().sleeper_base_url}/projections/nfl/regular/{SEASON}/{week}")
    r.raise_for_status()
    return {str(pid): stats for pid, stats in r.json().items() if isinstance(stats, dict) and stats}


def points(stats, weights):
    return sum(float(stats.get(k, 0.0)) * w for k, w in weights.items())


async def run(weeks, league_id):
    s = get_settings()
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await load_history(db, [2025, SEASON], datetime.now(timezone.utc))
        espn_league = s.espn_league_ids.split(",")[0].strip()
        cookies = {"espn_s2": s.espn_s2, "SWID": s.espn_swid} if s.espn_s2 else None
        async with httpx.AsyncClient(base_url=s.espn_fantasy_base_url, cookies=cookies, timeout=60) as ec, \
                httpx.AsyncClient(timeout=60) as sc:
            espn = {w: await espn_week(ec, espn_league, w) for w in weeks}
            sleeper = {w: await sleeper_week(sc, w) for w in weeks}
        espn_ids = await resolve_platform_players(db, "espn", sorted({i for v in espn.values() for i in v}))
        sleeper_ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
    sleeper_weights = offensive_weights(league.scoring_settings)
    internal = {CORE[k]: w for k, w in sleeper_weights.items() if k in CORE}
    slates = week_slates(history)
    rows = []  # (week, position, sleeper, espn, engine, actual)
    for w in weeks:
        if (SEASON, w) not in slates:
            continue
        cutoff, targets, actual = slates[(SEASON, w)]
        engine = compute(history, targets, cutoff, DEFAULT)
        e = {str(espn_ids[i].id): points(v, sleeper_weights) for i, v in espn[w].items() if espn_ids.get(i)}
        sl = {str(sleeper_ids[i].id): points(v, sleeper_weights) for i, v in sleeper[w].items() if sleeper_ids.get(i)}
        for pid, proj in engine.items():
            played, key = actual.get(pid), str(pid)
            if played is None or played.game_id != proj.game_id or key not in e or key not in sl:
                continue
            rows.append((w, proj.position, sl[key], e[key], score(proj.stats, internal), score(played.stats, internal)))
    # FantasyPros pool per (week, position) on the paired rows.
    pool = []
    groups = defaultdict(list)
    for r in rows:
        groups[(r[0], r[1])].append(r)
    for (w, pos), members in groups.items():
        n = POOL[pos]
        keep = {id(r) for r in sorted(members, key=lambda r: -r[2])[:n]} | {id(r) for r in sorted(members, key=lambda r: -r[5])[:n]}
        pool += [r for r in members if id(r) in keep]
    X = np.array([[r[2], r[3], r[4]] for r in pool])
    y = np.array([r[5] for r in pool])
    wk = np.array([r[0] for r in pool])
    pos = np.array([r[1] for r in pool])

    def mae(pred, mask=None):
        m = np.ones(len(y), bool) if mask is None else mask
        return round(float(np.mean(np.abs(pred[m] - y[m]))), 4)

    def lowo(cols):
        """Leave-one-week-out nonnegative weights (sum 1) by position, grid-searched."""
        grid = [np.array(v) for v in __import__("itertools").product(np.arange(0, 1.01, 0.1), repeat=len(cols))
                if abs(sum(v) - 1) < 1e-9]
        pred = np.zeros(len(y))
        chosen = {}
        for w in sorted(set(wk)):
            for p in sorted(set(pos)):
                train, test = (wk != w) & (pos == p), (wk == w) & (pos == p)
                if not test.any():
                    continue
                best = min(grid, key=lambda g: np.mean(np.abs(X[train][:, cols] @ g - y[train])))
                pred[test] = X[test][:, cols] @ best
                chosen.setdefault(p, []).append([round(float(v), 2) for v in best])
        return pred, chosen

    sources = {"sleeper": X[:, 0], "espn": X[:, 1], "engine": X[:, 2],
               "mean_sleeper_espn": X[:, :2].mean(1), "mean_all_three": X.mean(1)}
    lowo_two, chosen_two = lowo([0, 1])
    lowo_three, chosen_three = lowo([0, 1, 2])
    sources["lowo_sleeper_espn"], sources["lowo_all_three"] = lowo_two, lowo_three
    by_week = {name: {int(w): mae(p, wk == w) for w in sorted(set(wk))} for name, p in sources.items()}
    by_pos = {name: {p: mae(v, pos == p) for p in sorted(set(pos))} for name, v in sources.items()}
    return {"season": SEASON, "weeks": weeks, "league_id": league.league_id, "pool_rows": int(len(y)),
            "pool_mae": {name: mae(p) for name, p in sources.items()}, "by_week": by_week, "by_position": by_pos,
            "lowo_weights": {"sleeper_espn": chosen_two, "all_three": chosen_three},
            "weeks_consensus_beats_sleeper": sum(by_week["mean_sleeper_espn"][w] < by_week["sleeper"][w] for w in by_week["sleeper"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default="1-5")
    ap.add_argument("--league")
    a = ap.parse_args()
    lo, hi = map(int, a.weeks.split("-"))
    print(json.dumps(asyncio.run(run(list(range(lo, hi + 1)), a.league)), indent=1))


if __name__ == "__main__":
    main()
