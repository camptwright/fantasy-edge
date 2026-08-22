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

from src.models.facts import PlayerPropLine, TeamMarketLine


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
        # `observed_at` is a Python-side `datetime.now()` call (see
        # src/models/base.py's `utcnow`), not a DB-generated monotonic
        # sequence, so two observations for the same key could in principle
        # share a timestamp. ORDER BY observed_at DESC alone would then have
        # an undefined tiebreak - and this comparison is the entire
        # mechanism deciding write-vs-skip, so an arbitrary pick could
        # silently suppress a real line move or treat a stale row as
        # current. `id` isn't time-ordered either, but adding it as a
        # secondary key makes "latest" deterministic even under a tie -
        # not true first-write-wins (that needs a DB-generated monotonic
        # column, out of scope here), just a reproducible answer instead of
        # an arbitrary one. This codebase's sequential-await polling
        # pattern doesn't currently exercise a real collision.
        .order_by(desc(TeamMarketLine.observed_at), desc(TeamMarketLine.id))
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


async def record_prop_line(
    db: AsyncSession,
    *,
    player_id: uuid.UUID,
    game_id: uuid.UUID | None,
    stat_type: str,
    line: float,
    over_price_american: int | None,
    under_price_american: int | None,
    source: str,
) -> bool:
    """Write a prop observation only if it differs from the most recent one."""
    latest = await db.scalar(
        select(PlayerPropLine)
        .where(
            PlayerPropLine.player_id == player_id,
            PlayerPropLine.stat_type == stat_type,
            PlayerPropLine.source == source,
        )
        .order_by(desc(PlayerPropLine.observed_at))
        .limit(1)
    )
    if (
        latest is not None
        and latest.line == line
        and latest.over_price_american == over_price_american
        and latest.under_price_american == under_price_american
    ):
        return False

    db.add(
        PlayerPropLine(
            player_id=player_id,
            game_id=game_id,
            stat_type=stat_type,
            line=line,
            over_price_american=over_price_american,
            under_price_american=under_price_american,
            source=source,
        )
    )
    await db.flush()
    return True
