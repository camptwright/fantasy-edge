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
from src.services.quote_eligibility import confirm_quote


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
            # Closing and live are semantically different observation
            # types - a closing value that happens to equal the most
            # recent live value from the same source must still be written,
            # not silently suppressed as "unchanged". Omitting this let a
            # closing/live pair collapse into one row, breaking the ability
            # to compute closing-line value by comparing them.
            TeamMarketLine.line_type == line_type,
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
        await confirm_quote(db, 'team', latest)
        return False

    quote = TeamMarketLine(
            game_id=game_id,
            market=market,
            side=side,
            line=line,
            price_american=price_american,
            source=source,
            line_type=line_type,
        )
    db.add(quote)
    await db.flush()
    await confirm_quote(db, 'team', quote)
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
            PlayerPropLine.game_id == game_id,
        )
        # Same deterministic-tiebreak requirement as record_team_line()
        # above: `observed_at` is a Python-side `datetime.now()` call, not
        # a DB-generated monotonic sequence, so two rows can share a
        # timestamp. `id` as a secondary sort key makes "latest" a
        # reproducible answer instead of an arbitrary one.
        .order_by(desc(PlayerPropLine.observed_at), desc(PlayerPropLine.id))
        .limit(1)
    )
    if (
        latest is not None
        and latest.line == line
        and latest.over_price_american == over_price_american
        and latest.under_price_american == under_price_american
    ):
        await confirm_quote(db, 'prop', latest)
        return False

    quote = PlayerPropLine(
            player_id=player_id,
            game_id=game_id,
            stat_type=stat_type,
            line=line,
            over_price_american=over_price_american,
            under_price_american=under_price_american,
            source=source,
        )
    db.add(quote)
    await db.flush()
    await confirm_quote(db, 'prop', quote)
    return True
