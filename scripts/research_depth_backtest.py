"""Backtest projection_depth.adjust walk-forward on nflverse depth charts, rosters and injury reports.

projection_depth (the depth/status variant behind the workspace's engine
research column) was captured prospectively only, on the belief that no
historical depth charts exist. nflverse publishes all three live inputs:
- depth charts: ESPN-sourced daily snapshots (the latest one before each
  slate's cutoff, at most 10 days old), rank per position;
- weekly rosters: team and status (ACT, RES = reserve/IR, CUT, ...; INA, the
  game-day inactive list, is treated as active to avoid lookahead);
- injury reports: the final pregame designation.

Variants, graded on the promotion gate's pool (research_fixed_pool):
- proportional_*: Out/Doubtful players' targets and carries moved to RB/WR/TE
  teammates in proportion (research_vacated_volume), no other change;
- removals_only: rules 1-3 (unavailable, moved team, off chart), volumes kept;
- emulated: an independent re-implementation of the current rules 1-5;
- no_backup_rule: projection_depth.adjust without last-game starters (must
  match `emulated`);
- last_starter / depth_starter / agree_starter[_own]: one-passer QB rules
  (the backup-QB choice; projection_depth docstring rule 4);
- live_adjust: projection_depth.adjust itself, with last-game starters
  (must match `agree_starter_own`).

Results 2026-10-14 (league 1398509004950376448; 2025 n~2830, 2026 n~767):
the pre-2026-10-14 rules 4-5 (depth-one QB only; team volume capped at the
projected total, refill up to +50%) were worse than plain v1 by 0.17 (2025,
CI 0.10-0.23) and 0.21 (2026, CI 0.11-0.34); without the cap, 0.24 and 0.36.
Removals alone: no change. Proportional refill: alpha 0.75 best on 2025.

The raw depth-chart CSVs are ~60 MB a season, more than the worker's memory
limit alongside the engine history: compact them first (skill positions, last
snapshot per team-day; {team: {dt: {gsis: [pos, rank]}}}) and pass DEPTH_FILE.
Run in the worker environment:
    DEPTH_FILE=/tmp/depth_compact.json python -m scripts.research_depth_backtest [--league ID]
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
from src.services import projection_depth
from src.services.availability_rates import URL
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from scripts.diagnose_projection_engine import sleeper_week
from scripts.research_fixed_pool import bootstrap
from scripts.research_vacated_volume import redistribute
from scripts.tune_projection_engine import POOL, week_slates


async def reports(client, seasons):
    out = defaultdict(dict)  # (season, week) -> gsis -> status
    for season in seasons:
        r = await client.get(URL.format(season=season), follow_redirects=True)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            if row.get("game_type") == "REG" and row.get("report_status") and str(row.get("week")).isdigit():
                out[(season, int(row["week"]))][row["gsis_id"]] = row["report_status"]
    return out


ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv"
ACTIVE = {"ACT", "INA"}  # INA is the game-day inactive list (90 minutes pregame): treated as active, no lookahead


async def rosters(client, seasons):
    """(season, week) -> gsis -> (nflverse team code, roster status)."""
    out = defaultdict(dict)
    for season in seasons:
        r = await client.get(ROSTER_URL.format(season=season), follow_redirects=True)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            if row.get("game_type") == "REG" and row.get("gsis_id") and str(row.get("week")).isdigit():
                out[(season, int(row["week"]))][row["gsis_id"]] = (row["team"], row["status"])
    return out


DEPTH_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv"


async def depth_charts(client, seasons):
    """team -> sorted [(snapshot time, {gsis: (pos, rank)})], skill positions only (ESPN-sourced daily snapshots).

    DEPTH_FILE: a precompacted JSON {team: {dt: {gsis: [pos, rank]}}} (the raw CSVs are ~60 MB a season,
    more than the worker's memory limit allows alongside the engine history).
    """
    import os
    if os.environ.get("DEPTH_FILE"):
        raw = json.load(open(os.environ["DEPTH_FILE"]))
        return {team: sorted((datetime.fromisoformat(dt.replace("Z", "+00:00")), {g: tuple(v) for g, v in snap.items()})
                             for dt, snap in snaps.items()) for team, snaps in raw.items()}
    snaps = defaultdict(lambda: defaultdict(dict))
    for season in seasons:
        r = await client.get(DEPTH_URL.format(season=season), follow_redirects=True, timeout=300)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            if row.get("pos_abb") in ("QB", "RB", "WR", "TE") and row.get("gsis_id") and row.get("pos_rank", "").isdigit():
                t = datetime.fromisoformat(row["dt"].replace("Z", "+00:00"))
                cur = snaps[row["team"]][t].get(row["gsis_id"])
                rank = int(row["pos_rank"])
                if cur is None or rank < cur[1]:
                    snaps[row["team"]][t][row["gsis_id"]] = (row["pos_abb"], rank)
    return {team: sorted(v.items()) for team, v in snaps.items()}


def chart_at(charts, cutoff):
    """gsis -> (team, pos, rank) from each team's latest snapshot before cutoff (at most 10 days old)."""
    out = {}
    for team, series in charts.items():
        prior = [(t, v) for t, v in series if t < cutoff]
        if prior and (cutoff - prior[-1][0]).days <= 10:
            for g, (pos, rank) in prior[-1][1].items():
                out[g] = (team, pos, rank)
    return out


def qb_handoff(proj, kept, gone, depth):
    """Only when a team's projected starter (most projected attempts) is out: the top remaining QB by
    depth order inherits the starter's passing volume. Otherwise QBs are untouched."""
    by_team = defaultdict(list)
    for p in proj.values():
        if p.position == "QB":
            by_team[(p.game_id, p.team_id)].append(p)
    out = dict(kept)
    for members in by_team.values():
        starter = max(members, key=lambda p: p.stats.get("passing_attempts", 0.0))
        if starter.player_id not in gone:
            continue
        live = [p for p in members if p.player_id in out and p.player_id not in gone]
        if not live:
            continue
        heir = min(live, key=lambda p: (depth[p.player_id].depth_order or 99, -p.stats.get("passing_attempts", 0.0)))
        own = heir.stats.get("passing_attempts", 0.0)
        if own > 0:
            f = starter.stats["passing_attempts"] / own
            out[heir.player_id] = replace(out[heir.player_id], stats=projection_depth._scale(out[heir.player_id].stats, projection_depth.PASSING, f))
    return out


async def run(league_id):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await engine.load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
        slates = week_slates(history)
        keys = sorted(k for k in slates if k[0] in (2025, 2026))
        async with httpx.AsyncClient(timeout=120) as c:
            sleeper = {k: await sleeper_week(c, *k) for k in keys}
            report = await reports(c, (2025, 2026))
            roster = await rosters(c, (2025, 2026))
            charts = await depth_charts(c, (2025, 2026))
        ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
        from src.services.team_model_serving import team_codes
        code_team = {code: tid for tid, code in (await team_codes(db)).items() if code}
        gsis = dict((await db.execute(select(Player.gsis_id, Player.id).where(Player.sport == "nfl", Player.gsis_id.is_not(None)))).all())
    sw = offensive_weights(league.scoring_settings)
    wbs = {CORE[k]: w for k, w in sw.items() if k in CORE}
    spts = {k: {ids[i].id: sum(float(s.get(a, 0)) * w for a, w in sw.items()) for i, s in v.items() if ids.get(i)} for k, v in sleeper.items()}
    pools, base = {}, {}
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
        base[k] = engine.compute(history, targets, cutoff, engine.DEFAULT)

    # (slate, team) -> the QB with the most pass attempts in the team's last game before the cutoff.
    last_qb = {}
    team_last = {}
    for k in keys:
        cutoff = slates[k][0]
        for t in history.teams.values():
            if t.kickoff < cutoff and (k, t.team_id) not in team_last or (t.kickoff < cutoff and t.kickoff > team_last[(k, t.team_id)].kickoff):
                team_last[(k, t.team_id)] = t
    by_game_team = defaultdict(list)
    for pg in history.players.values():
        if history.positions.get(pg.player_id) == "QB":
            by_game_team[(pg.game_id, pg.team_id)].append(pg)
    for (k, team), t in team_last.items():
        qbs = by_game_team.get((t.game_id, team))
        if qbs:
            last_qb[(k, team)] = max(qbs, key=lambda pg: pg.stats.get("passing_attempts", 0.0)).player_id

    def variant(name):
        out = {}
        for k in keys:
            proj, rep = base[k], {gsis[g]: s for g, s in report.get(k, {}).items() if g in gsis}
            if name == "default":
                out[k] = proj
                continue
            out_now = {pid for pid in proj if rep.get(pid) in projection_depth.VACATING}
            if name.startswith("proportional"):
                out[k] = redistribute(proj, out_now, float(name.split("_")[1]))
                continue
            # The live inputs: depth chart as of the cutoff, weekly roster status, final injury report.
            ros = {gsis[g]: v for g, v in roster.get(k, {}).items() if g in gsis}
            chart = {gsis[g]: v for g, v in chart_at(charts, slates[k][0]).items() if g in gsis}
            depth = {}
            for pid, p in proj.items():
                team, status = ros.get(pid, (None, None))
                c_team, c_pos, c_rank = chart.get(pid, (None, None, None))
                depth[pid] = projection_depth.DepthStatus(
                    code_team.get(c_team or team) if (c_team or team) else None,
                    "Active" if status in ACTIVE or (status is None and c_team) else "Inactive",
                    rep.get(pid), c_pos, c_rank)
            starters = {team: pid for (kk, team), pid in last_qb.items() if kk == k}
            adjusted, removed = projection_depth.adjust(proj, depth)
            if name == "live_adjust":
                out[k] = projection_depth.adjust(proj, depth, starters=starters)[0]
            elif name == "no_backup_rule":
                out[k] = adjusted
            elif name == "removals_only":  # rules 1-3, volumes untouched
                out[k] = {pid: p for pid, p in proj.items() if pid not in removed}
            elif name in ("last_starter", "depth_starter", "agree_starter", "agree_starter_own"):
                # One passer per team. last_starter: the QB with the most attempts in the team's last
                # game if still available, else the top available QB by depth order (then projected
                # attempts). depth_starter: depth order only (the pre-2026-10-14 rule 4 choice).
                # The starter takes the projected starter volume; every other QB passes nothing.
                adj = dict(adjusted)
                gone = out_now | set(removed)
                by_team = defaultdict(list)
                for p in proj.values():
                    if p.position == "QB":
                        by_team[(p.game_id, p.team_id)].append(p)
                for (gid, team), members in by_team.items():
                    live = [p for p in members if p.player_id in adj and p.player_id not in gone]
                    if not live:
                        continue
                    last = last_qb.get((k, team)) if name != "depth_starter" else None
                    by_depth = min(live, key=lambda p: (depth[p.player_id].depth_order or 99, -p.stats.get("passing_attempts", 0.0)))
                    if name.startswith("agree_starter"):
                        # Only when the depth chart's top available QB also started the team's last game.
                        if by_depth.player_id != last or depth[by_depth.player_id].depth_order is None:
                            continue
                        starter = by_depth
                    else:
                        starter = next((p for p in live if p.player_id == last), None) or by_depth
                    volume = max(p.stats.get("passing_attempts", 0.0) for p in members)
                    for p in live:
                        own = adj[p.player_id].stats.get("passing_attempts", 0.0)
                        f = ((1.0 if name == "agree_starter_own" else volume / own) if own > 0 else 0.0) if p is starter else 0.0
                        adj[p.player_id] = replace(adj[p.player_id], stats=projection_depth._scale(adj[p.player_id].stats, projection_depth.PASSING, f))
                out[k] = adj
            elif name == "emulated":  # independent re-implementation of rules 1-5, to check live_adjust
                kept = {pid: p for pid, p in redistribute(proj, out_now, projection_depth.REFILL).items() if pid not in removed}
                out[k] = qb_handoff(proj, kept, out_now | set(removed), depth)
        return out

    def rows(projs):
        r = []
        for k in keys:
            actual = slates[k][2]
            for pid in pools[k]:
                p = projs[k].get(pid)
                if p is not None and p.game_id == actual[pid].game_id:
                    r.append((k, p.position, engine.score(p.stats, wbs), engine.score(actual[pid].stats, wbs), pid))
        return r

    b = {(x[0], x[4]): x for x in rows(variant("default"))}
    out = {}
    for name in ("default", "proportional_0.75", "removals_only", "emulated", "no_backup_rule", "live_adjust", "last_starter", "depth_starter", "agree_starter", "agree_starter_own"):
        r = rows(variant(name))
        res = {}
        for season in (2025, 2026):
            s = [x for x in r if x[0][0] == season and (x[0], x[4]) in b]
            by_week = defaultdict(list)
            for x in s:
                base_row = b[(x[0], x[4])]
                by_week[x[0]].append(abs(x[2] - x[3]) - abs(base_row[2] - x[3]))
            res[str(season)] = {"n": len(s), "mae": round(float(np.mean([abs(x[2] - x[3]) for x in s])), 4),
                                "vs_default_ci": bootstrap({k: np.array(v) for k, v in by_week.items()}),
                                "by_position": {p: round(float(np.mean([abs(x[2] - x[3]) for x in s if x[1] == p])), 3) for p in POOL}}
        out[name] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1))


if __name__ == "__main__":
    main()
