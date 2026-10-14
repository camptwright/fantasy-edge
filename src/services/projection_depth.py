"""Depth-chart and roster-status adjustment for projection engine v1 (E3 amendment).

The v1 walk-forward's real flaws were healthy backups and fringe players
getting a typical player's share, and a per-team share cap failed because
the engine could not tell who was active (docs/2026-10-06-overhaul-status-
and-ui-direction.md, "E3 amended"). Sleeper's catalog carries the missing
inputs: `status`, `injury_status`, `team`, `depth_chart_position`,
`depth_chart_order`. This module post-adjusts v1 output with them:

1. Unavailable: a non-Active status or a definitive designation (Out, IR,
   PUP, suspended, NFI) removes the player. Questionable/Doubtful stay in
   (conditional on playing; availability_rates gives the play probability).
2. Moved: a player whose catalog team is no longer the projected team is
   removed from that team.
3. Off the depth chart: removed, but only where the team has depth-charted
   players at that position, so a missing chart never empties a team.
4. QB: when the projected starter (most projected attempts) is gone, the
   top remaining QB by depth order inherits his passing volume. Backups pass
   nothing only when the depth chart's top available QB also started the
   team's last game, or last game's starter is ruled out; if the chart and
   the last start disagree, every QB keeps his projection. This
   costs ~0.1 points on graded QBs (relief appearances after an in-game
   injury score but were projected 0) and keeps backups from showing a
   starter's projection.
5. Vacated volume: the targets and carries of players designated Out or
   Doubtful for this game go to the remaining RB/WR/TE in proportion to
   their own projections, times REFILL. There is no team-volume cap.

Backtest (scripts/research_depth_backtest.py, 2026-10-14): nflverse's daily
depth charts, weekly roster status and final injury reports reproduce these
inputs walk-forward. The earlier rules 4-5 (only the depth-one QB passes;
team targets/carries capped at projected team volume and refilled up to
+50%) were worse than plain v1 on the promotion pool by 0.17 points (2025,
CI 0.10-0.23) and 0.21 (2026, CI 0.11-0.34): the cap scaled starters down
whenever stale players stayed on a team, and only the depth-one QB passed.
The current rules are level with plain v1: +0.01 (2025, CI -0.05 to +0.03)
and -0.03 (2026, CI -0.07 to +0.02); without the backup-QB rule -0.01 and
-0.04. Removals (1-3) alone change nothing for players who played. REFILL
was chosen on 2025 only. What the variant adds is presentation: ruled-out,
moved and off-chart players and backup QBs no longer show a starter's line.

Captured prospectively beside v1 under its own version and graded by the
same harness. Never promoted automatically.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game
from src.models.identity import Team
from src.services.game_environment import environments
from src.services.projection_engine import DEFAULT, Params, Projection, compute, load_history

RECIPE = "projection_engine_v1_depth"
UNAVAILABLE = {"Out", "IR", "PUP", "Sus", "NFI", "NA", "DNR", "COV"}
# Designations that span more than one game, for projecting later weeks.
LONG_TERM = UNAVAILABLE - {"Out"}
# This-game designations whose holder's targets and carries pass to teammates, and the share
# passed on (scripts/research_depth_backtest.py, chosen on 2025: 0.75). Long-term statuses
# (IR, PUP, ...) are not included: teammates' recent shares already absorb a long absence.
VACATING = {"Out", "Doubtful"}
REFILL = 0.75
RECEIVING = ("targets", "receptions", "receiving_yards", "receiving_touchdowns", "receiving_2pt_conversions")
RUSHING = ("rushing_attempts", "rushing_yards", "rushing_touchdowns", "rushing_2pt_conversions")
PASSING = ("passing_attempts", "passing_completions", "passing_yards", "passing_touchdowns",
           "passing_interceptions", "passing_2pt_conversions")
ALIAS = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}


@dataclass(frozen=True)
class DepthStatus:
    team_id: uuid.UUID | None
    status: str | None
    injury_status: str | None
    depth_position: str | None
    depth_order: int | None

    def available(self, unavailable: frozenset[str] | set[str] = UNAVAILABLE) -> bool:
        return (self.status in (None, "Active")) and self.injury_status not in unavailable


def _scale(stats: dict[str, float], keys: tuple[str, ...], factor: float) -> dict[str, float]:
    return {k: (v * factor if k in keys else v) for k, v in stats.items()}


def _touches(stats: dict[str, float]) -> float:
    return stats.get("targets", 0.0) + stats.get("rushing_attempts", 0.0) + 0.1 * stats.get("passing_attempts", 0.0)


def last_starters(history, cutoff: datetime) -> dict[uuid.UUID, uuid.UUID]:
    """Team id -> the QB with the most pass attempts in the team's latest game before cutoff."""
    latest: dict[uuid.UUID, object] = {}
    for t in history.teams.values():
        if t.kickoff < cutoff and (t.team_id not in latest or t.kickoff > latest[t.team_id].kickoff):
            latest[t.team_id] = t
    wanted = {(t.game_id, t.team_id) for t in latest.values()}
    best: dict[uuid.UUID, tuple[float, uuid.UUID]] = {}
    for p in history.players.values():
        if (p.game_id, p.team_id) in wanted and history.positions.get(p.player_id) == "QB":
            attempts = p.stats.get("passing_attempts", 0.0)
            if p.team_id not in best or attempts > best[p.team_id][0]:
                best[p.team_id] = (attempts, p.player_id)
    return {team: pid for team, (_, pid) in best.items()}


def adjust(projections: dict[uuid.UUID, Projection], depth: dict[uuid.UUID, DepthStatus],
           unavailable: set[str] = UNAVAILABLE, vacating: set[str] = VACATING,
           starters: dict[uuid.UUID, uuid.UUID] | None = None,
           ) -> tuple[dict[uuid.UUID, Projection], dict[uuid.UUID, str]]:
    """Pure core. Returns (adjusted projections, {removed player: reason}).

    Players with no catalog entry are kept unchanged: unknown is not inactive.
    `unavailable` is the set of designations that remove a player; later
    weeks use LONG_TERM, since an Out designation covers one game. `vacating`
    designations pass a player's targets and carries to teammates (empty for
    later weeks). `starters`: team id -> last game's starting QB (last_starters).
    """
    removed: dict[uuid.UUID, str] = {}
    by_team: dict[tuple, list[Projection]] = defaultdict(list)
    for p in projections.values():
        by_team[(p.game_id, p.team_id)].append(p)
    out: dict[uuid.UUID, Projection] = {}
    for (_, team_id), members in by_team.items():
        charted = {p.position for p in members
                   if (d := depth.get(p.player_id)) and d.team_id == team_id and d.depth_order is not None}
        keep: list[Projection] = []
        for p in members:
            d = depth.get(p.player_id)
            if d is None:
                keep.append(p)
            elif not d.available(unavailable):
                removed[p.player_id] = "unavailable"
            elif d.team_id is not None and d.team_id != team_id:
                removed[p.player_id] = "moved_team"
            elif d.depth_order is None and p.position in charted:
                removed[p.player_id] = "off_depth_chart"
            else:
                keep.append(p)
        stats = {p.player_id: dict(p.stats) for p in keep}
        gone = {pid for pid, d in depth.items() if d.injury_status in vacating} | set(removed)
        # QB: only when the projected starter (most projected attempts) is gone does the top
        # remaining QB by depth order inherit his passing volume; otherwise QBs are untouched.
        qbs = [p for p in members if p.position == "QB"]
        if qbs:
            starter = max(qbs, key=lambda p: p.stats.get("passing_attempts", 0.0))
            heirs = [p for p in keep if p.position == "QB" and p.player_id not in gone]
            if starter.player_id in gone and heirs:
                heir = min(heirs, key=lambda p: (
                    depth[p.player_id].depth_order if p.player_id in depth and depth[p.player_id].depth_order is not None else 99,
                    -p.stats.get("passing_attempts", 0.0)))
                own = heir.stats.get("passing_attempts", 0.0)
                if own > 0:
                    stats[heir.player_id] = _scale(stats[heir.player_id], PASSING,
                                                   starter.stats.get("passing_attempts", 0.0) / own)
            # Backups: when the depth chart's top available QB also started the team's last game
            # (or last game's starter is ruled out), the other QBs pass nothing. When the two disagree (benched starter, a return from
            # injury) the starter is uncertain and every QB keeps his conditional projection.
            available = [p for p in keep if p.position == "QB" and p.player_id not in gone]
            charted_qbs = [p for p in available if p.player_id in depth and depth[p.player_id].depth_order is not None]
            if charted_qbs and starters is not None:
                top = min(charted_qbs, key=lambda p: (depth[p.player_id].depth_order,
                                                       -p.stats.get("passing_attempts", 0.0)))
                last = starters.get(team_id)
                # Last game's starter is the top available QB, or he is the one ruled out (the heir is clear).
                if last == top.player_id or last in gone:
                    for p in available:
                        if p.player_id != top.player_id:
                            stats[p.player_id] = _scale(stats[p.player_id], PASSING, 0.0)
        # Vacated volume: targets and carries of players ruled out for this game go to the
        # remaining RB/WR/TE in proportion to their own, times REFILL. No team-volume cap.
        receivers = [p.player_id for p in keep if p.position in ("RB", "WR", "TE") and p.player_id not in gone]
        for stat, keys in (("targets", RECEIVING), ("rushing_attempts", RUSHING)):
            vacated = sum(p.stats.get(stat, 0.0) for p in members
                          if p.position != "QB" and p.player_id in gone and depth[p.player_id].injury_status in vacating)
            total = sum(stats[pid].get(stat, 0.0) for pid in receivers)
            if vacated <= 0 or total <= 0:
                continue
            factor = 1 + REFILL * vacated / total
            for pid in receivers:
                stats[pid] = _scale(stats[pid], keys, factor)
        for p in keep:
            before, after = _touches(p.stats), _touches(stats[p.player_id])
            if before > 0:
                stats[p.player_id]["fumbles_lost"] = p.stats.get("fumbles_lost", 0.0) * after / before
            out[p.player_id] = replace(p, stats=stats[p.player_id])
    return out, removed


async def depth_inputs(db: AsyncSession, catalog: dict[str, dict]) -> dict[uuid.UUID, DepthStatus]:
    """Sleeper catalog (player_id -> fields) to canonical player ids."""
    from src.services.player_identity import resolve_platform_players
    relevant = {pid: info for pid, info in catalog.items()
                if isinstance(info, dict) and info.get("position") in ("QB", "RB", "WR", "TE")}
    resolved = await resolve_platform_players(db, "sleeper", sorted(relevant))
    teams = (await db.scalars(select(Team).where(Team.sport == "nfl"))).all()
    team_by_abbr = {ALIAS.get(t.nflverse_abbr, t.nflverse_abbr): t.id for t in teams if t.nflverse_abbr}
    out = {}
    for pid, player in resolved.items():
        info = relevant[pid]
        abbr = info.get("team")
        order = info.get("depth_chart_order")
        out[player.id] = DepthStatus(
            team_id=team_by_abbr.get(ALIAS.get(abbr, abbr)) if abbr else None,
            status=info.get("status"), injury_status=info.get("injury_status"),
            depth_position=info.get("depth_chart_position"),
            depth_order=int(order) if isinstance(order, (int, float)) else None)
    return out


async def project(db: AsyncSession, target_games: list[Game], cutoff: datetime,
                  depth: dict[uuid.UUID, DepthStatus], *, params: Params = DEFAULT):
    """v1 projections for target_games, then the depth/status adjustment."""
    seasons = sorted({g.season for g in target_games} | {min(g.season for g in target_games) - 1})
    history = await load_history(db, seasons, cutoff)
    env = await environments(db, [g.id for g in target_games], as_of=cutoff)
    targets = [(g, env[g.id].home_points, env[g.id].away_points, env[g.id].home_spread)
               for g in target_games if g.id in env]
    base = compute(history, targets, cutoff, params)
    return adjust(base, depth, starters=last_starters(history, cutoff))
