"""Append-only line writes, deduplicated on value rather than on time.

There is deliberately no unique index backing this. A line can move away and
return to a previous value, and that return is genuine market movement; a
unique constraint on (game, market, side, source, line, price) would reject
it. The comparison is therefore against the LATEST observation only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import TeamMarketLine


async def record_team_line(
    db: AsyncSession,
    *,
    game_id: uuid.UUID,
    market: str,
    side: str,
    line: float | None,
    price_american: int | None,
    source: str,
    line_type: str,
) -> bool:
    """Write an observation only if it differs from the most recent one."""
    latest = await db.scalar(
        select(TeamMarketLine)
        .where(
            TeamMarketLine.game_id == game_id,
            TeamMarketLine.market == market,
            TeamMarketLine.side == side,
            TeamMarketLine.source == source,
        )
        .order_by(desc(TeamMarketLine.observed_at))
        .limit(1)
    )
    if (
        latest is not None
        and latest.line == line
        and latest.price_american == price_american
    ):
        return False

    db.add(
        TeamMarketLine(
            game_id=game_id,
            market=market,
            side=side,
            line=line,
            price_american=price_american,
            source=source,
            line_type=line_type,
        )
    )
    await db.flush()
    return True
