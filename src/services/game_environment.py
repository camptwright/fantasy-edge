"""Implied team points from stored spread and total lines.

The projection engine's game environment: a team's implied points set its
expected volume and touchdown opportunity. Uses team_market_lines' sign
convention (see src/models/facts.py): the home spread line is negative when
the home team is favoured, so implied home = total/2 - home_line/2.

Point-in-time: only observations at or before `as_of` are used, so a
backtest reading this at kickoff cannot see a later line. Spread and total
must come from the same source; mixing books would pair numbers no single
market ever offered together.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import TeamMarketLine

# Sharpest first. nflverse closing lines are the historical fallback.
SOURCE_PRIORITY = ("pinnacle", "theodds", "bovada", "espn", "nflverse")


@dataclass(frozen=True)
class GameEnvironment:
    game_id: uuid.UUID
    home_points: float
    away_points: float
    total: float
    home_spread: float
    source: str
    observed_at: datetime


def implied_points(total: float, home_spread: float) -> tuple[float, float]:
    """(home, away) implied points; home_spread is the home side's handicap."""
    return total / 2 - home_spread / 2, total / 2 + home_spread / 2


async def environments(
    db: AsyncSession, game_ids: list[uuid.UUID], *,
    as_of: datetime | dict[uuid.UUID, datetime],
) -> dict[uuid.UUID, GameEnvironment]:
    """Latest same-source spread+total per game observed at or before as_of.

    `as_of` may be one cutoff for every game or a per-game mapping (e.g.
    each historical game's own kickoff). Games with no qualifying pair are
    absent from the result, never defaulted to a league-average total.
    """
    if not game_ids:
        return {}
    cutoff = as_of if isinstance(as_of, dict) else dict.fromkeys(game_ids, as_of)
    rows = (await db.execute(
        select(TeamMarketLine.game_id, TeamMarketLine.market, TeamMarketLine.line,
               TeamMarketLine.source, TeamMarketLine.observed_at)
        .where(TeamMarketLine.game_id.in_(game_ids),
               TeamMarketLine.observed_at <= max(cutoff.values()),
               TeamMarketLine.line.is_not(None),
               ((TeamMarketLine.market == "spread") & (TeamMarketLine.side == "home"))
               | ((TeamMarketLine.market == "total") & (TeamMarketLine.side == "over")))
        .order_by(TeamMarketLine.observed_at)
    )).all()
    latest: dict[tuple, tuple[float, datetime]] = {}
    for game_id, market, line, source, observed in rows:
        if observed > cutoff[game_id]:
            continue
        latest[(game_id, source, market)] = (line, observed)  # ascending order: last wins

    result: dict[uuid.UUID, GameEnvironment] = {}
    for game_id in game_ids:
        for source in SOURCE_PRIORITY:
            spread = latest.get((game_id, source, "spread"))
            total = latest.get((game_id, source, "total"))
            if spread is None or total is None:
                continue
            home, away = implied_points(total[0], spread[0])
            result[game_id] = GameEnvironment(
                game_id=game_id, home_points=home, away_points=away, total=total[0],
                home_spread=spread[0], source=source, observed_at=max(spread[1], total[1]))
            break
    return result
