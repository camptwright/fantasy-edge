"""Redistribute ruled-out teammates' volume (projection engine v1, walk-forward).

The engine projects every player last seen on a team and does not know who is
inactive, so when a starter is ruled out his targets and carries are not
passed on (diagnose_projection_engine: with >= 6 vacated targets the engine's
pool bias is -2.4 points against -1.3 for Sleeper). Pregame information only:
nflverse's official weekly injury reports (final game status Out or Doubtful,
published before kickoff), not who actually played.

Variant alpha: the ruled-out players' projected targets (carries) are moved
to same-team teammates at the same rate positions, in proportion to each
teammate's projected targets (carries), times alpha. Target-derived stats
scale with the target factor, carry-derived stats with the carry factor.
QBs' passing is left alone (a backup QB's projection is a separate problem).
Graded on the promotion gate's pool (research_fixed_pool).
Run in the worker environment: python -m scripts.research_vacated_volume [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import numpy as np
from sqlalchemy import select

import src.services.projection_engine as engine
from src.db.client import get_worker_db
from src.models.identity import Player
from src.models.sleeper import SleeperLeague
from src.services.availability_rates import URL
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from scripts.diagnose_projection_engine import sleeper_week
from scripts.research_fixed_pool import bootstrap
from scripts.tune_projection_engine import POOL, week_slates

RULED_OUT = {"Out", "Doubtful"}
TARGET_STATS = ("targets", "receptions", "receiving_yards", "receiving_touchdowns", "receiving_2pt_conversions")
CARRY_STATS = ("rushing_attempts", "rushing_yards", "rushing_touchdowns", "rushing_2pt_conversions")


async def ruled_out(client, seasons):
    """(season, week) -> set of gsis ids ruled out on the final report."""
    out = defaultdict(set)
    for season in seasons:
        r = await client.get(URL.format(season=season), follow_redirects=True)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            if row.get("game_type") == "REG" and row.get("report_status") in RULED_OUT and str(row.get("week")).isdigit():
                out[(season, int(row["week"]))].add(row["gsis_id"])
    return out


def redistribute(proj, out_ids, alpha):
    by_team = defaultdict(list)
    for pid, p in proj.items():
        by_team[p.team_id].append(pid)
    new = dict(proj)
    for team, members in by_team.items():
        gone = [pid for pid in members if pid in out_ids]
        if not gone:
            continue
        live = [pid for pid in members if pid not in out_ids and proj[pid].position in ("RB", "WR", "TE")]
        for volume, stats in (("targets", TARGET_STATS), ("rushing_attempts", CARRY_STATS)):
            vacated = sum(proj[pid].stats.get(volume, 0.0) for pid in gone if proj[pid].position != "QB")
            total = sum(new[pid].stats.get(volume, 0.0) for pid in live)
            if vacated <= 0 or total <= 0:
                continue
            factor = 1 + alpha * vacated / total
            for pid in live:
                s = dict(new[pid].stats)
                for k in stats:
                    s[k] = s.get(k, 0.0) * factor
                if volume == "targets" or volume == "rushing_attempts":
                    s["fumbles_lost"] = new[pid].stats.get("fumbles_lost", 0.0)  # leave tiny term alone
                new[pid] = replace(new[pid], stats=s)
    return new


async def run(league_id):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await engine.load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
        slates = week_slates(history)
        keys = sorted(k for k in slates if k[0] in (2025, 2026))
        async with httpx.AsyncClient(timeout=120) as c:
            sleeper = {k: await sleeper_week(c, *k) for k in keys}
            reports = await ruled_out(c, (2025, 2026))
        ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
        gsis = dict((await db.execute(select(Player.gsis_id, Player.id).where(Player.sport == "nfl", Player.gsis_id.is_not(None)))).all())
    sw = offensive_weights(league.scoring_settings)
    wbs = {CORE[k]: w for k, w in sw.items() if k in CORE}
    spts = {k: {ids[i].id: sum(float(s.get(a, 0)) * w for a, w in sw.items()) for i, s in v.items() if ids.get(i)} for k, v in sleeper.items()}
    pools, projections = {}, {}
    for k in keys:
        cutoff, targets, actual = slates[k]
        groups = defaultdict(list)
        for pid, played in actual.items():
            pos = history.positions.get(pid)
            if pos in POOL and pid in spts[k]:
                groups[pos].append((pid, spts[k][pid], engine.score(played.stats, wbs)))
        chosen = set()
        for pos, m in groups.items():
            chosen |= {x[0] for x in sorted(m, key=lambda x: -x[1])[:POOL[pos]]} | {x[0] for x in sorted(m, key=lambda x: -x[2])[:POOL[pos]]}
        pools[k] = chosen
        projections[k] = engine.compute(history, targets, cutoff, engine.DEFAULT)
    out_ids = {k: {gsis[g] for g in reports.get(k, ()) if g in gsis} for k in keys}

    def grade(alpha):
        rows = []
        for k in keys:
            proj = redistribute(projections[k], out_ids[k], alpha) if alpha else projections[k]
            actual = slates[k][2]
            for pid in pools[k]:
                p = proj.get(pid)
                if p is None or p.game_id != actual[pid].game_id:
                    continue
                rows.append((k, p.position, engine.score(p.stats, wbs), engine.score(actual[pid].stats, wbs), pid))
        return rows

    base = grade(0.0)
    bmap = {(r[0], r[4]): r for r in base}
    changed_keys = None
    out = {"ruled_out_matched": sum(len(v) for v in out_ids.values())}
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        rows = grade(alpha)
        res = {}
        for season in (2025, 2026):
            r = [x for x in rows if x[0][0] == season]
            by_week = defaultdict(list)
            changed = []
            for x in r:
                b = bmap[(x[0], x[4])]
                d = abs(x[2] - x[3]) - abs(b[2] - x[3])
                by_week[x[0]].append(d)
                if abs(x[2] - b[2]) > 1e-9:
                    changed.append((abs(x[2] - x[3]), abs(b[2] - x[3]), x[2] - x[3], b[2] - x[3]))
            res[str(season)] = {"n": len(r), "mae": round(float(np.mean([abs(x[2] - x[3]) for x in r])), 4),
                                "vs_default_ci": bootstrap({k: np.array(v) for k, v in by_week.items()}),
                                "changed_rows": len(changed),
                                "changed_mae": [round(float(np.mean([c[0] for c in changed])), 3), round(float(np.mean([c[1] for c in changed])), 3)] if changed else None,
                                "changed_bias": [round(float(np.mean([c[2] for c in changed])), 3), round(float(np.mean([c[3] for c in changed])), 3)] if changed else None,
                                "by_position": {p: round(float(np.mean([abs(x[2] - x[3]) for x in r if x[1] == p])), 3) for p in POOL}}
        out[f"alpha_{alpha}"] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1))


if __name__ == "__main__":
    main()
