"""Per player-game opportunity shares: snap share, target share, carry share.

Team membership for a game comes from player_snap_counts (the team the
player actually played for), and team volume is summed over the players
with snap rows in that game. A player with stats but no snap row is left
out of both numerator and denominator rather than guessed onto a team.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game, PlayerGameStat, PlayerSnapCount

VOLUME_STATS = ("targets", "rushing_attempts", "passing_attempts")


@dataclass(frozen=True)
class PlayerGameUsage:
    player_id: uuid.UUID
    game_id: uuid.UUID
    team_id: uuid.UUID
    season: int
    week: int | None
    snap_share: float
    target_share: float | None  # None when the team recorded no targets
    carry_share: float | None
    team_offense_snaps: int
    team_targets: float
    team_carries: float
    team_pass_attempts: float


def team_snaps(rows: list[tuple[int, float]]) -> int:
    """Team offensive plays from (player snaps, player pct) pairs.

    snaps/pct recovers the team total from any one player; the median over
    players absorbs PFR's rounding of pct to two decimals.
    """
    estimates = [snaps / pct for snaps, pct in rows if pct > 0]
    return round(median(estimates)) if estimates else 0


def shares(snaps: list[dict], stats: dict[tuple, dict[str, float]]) -> list[PlayerGameUsage]:
    """Pure core: snaps rows + {(player_id, game_id): {stat: value}} -> usage rows."""
    by_team: dict[tuple, list[dict]] = defaultdict(list)
    for row in snaps:
        by_team[(row["game_id"], row["team_id"])].append(row)
    out = []
    for (game_id, team_id), members in by_team.items():
        totals = {s: sum(stats.get((m["player_id"], game_id), {}).get(s, 0.0) for m in members)
                  for s in VOLUME_STATS}
        plays = team_snaps([(m["offense_snaps"], m["offense_pct"]) for m in members])
        for m in members:
            own = stats.get((m["player_id"], game_id), {})
            out.append(PlayerGameUsage(
                player_id=m["player_id"], game_id=game_id, team_id=team_id,
                season=m["season"], week=m["week"], snap_share=m["offense_pct"],
                target_share=own.get("targets", 0.0) / totals["targets"] if totals["targets"] else None,
                carry_share=(own.get("rushing_attempts", 0.0) / totals["rushing_attempts"]
                             if totals["rushing_attempts"] else None),
                team_offense_snaps=plays, team_targets=totals["targets"],
                team_carries=totals["rushing_attempts"], team_pass_attempts=totals["passing_attempts"]))
    return out


async def season_usage(db: AsyncSession, season: int) -> list[PlayerGameUsage]:
    snap_rows = (await db.execute(
        select(PlayerSnapCount.player_id, PlayerSnapCount.game_id, PlayerSnapCount.team_id,
               PlayerSnapCount.offense_snaps, PlayerSnapCount.offense_pct, Game.season, Game.week)
        .join(Game, Game.id == PlayerSnapCount.game_id)
        .where(Game.sport == "nfl", Game.season == season)
    )).mappings().all()
    stat_rows = (await db.execute(
        select(PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type,
               PlayerGameStat.value)
        .join(Game, Game.id == PlayerGameStat.game_id)
        .where(Game.sport == "nfl", Game.season == season,
               PlayerGameStat.stat_type.in_(VOLUME_STATS))
    )).all()
    stats: dict[tuple, dict[str, float]] = defaultdict(dict)
    for player_id, game_id, stat_type, value in stat_rows:
        stats[(player_id, game_id)][stat_type] = value
    return shares([dict(r) for r in snap_rows], stats)
