"""Persistence boundary for normalized provider observations."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.providers.base import NormalizedMarket
from src.models.orm import OddsSnapshot


async def persist_market_snapshots(
    db: AsyncSession,
    records: Iterable[NormalizedMarket],
    *,
    game_ids: dict[tuple[str, str], UUID] | None = None,
) -> list[OddsSnapshot]:
    """Append normalized observations; never update an existing snapshot.

    `game_ids` is keyed by `(provider, external_event_id)` and is optional while
    identity resolution is incomplete. A missing game link is retained rather
    than silently dropping the market observation.
    """

    rows: list[OddsSnapshot] = []
    for record in records:
        game_id = (game_ids or {}).get((record.provider, record.external_event_id))
        row = OddsSnapshot(
            game_id=game_id,
            sport=record.sport,
            bookmaker=record.bookmaker,
            market=record.market,
            outcome=record.outcome,
            price_american=record.price_american,
            price_decimal=record.price_decimal,
            point=record.point,
        )
        db.add(row)
        rows.append(row)
    if rows:
        await db.flush()
    return rows
