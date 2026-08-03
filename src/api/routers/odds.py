from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.serializers import row_to_dict
from src.data.cache.db_client import get_db
from src.models.orm import OddsSnapshot

router = APIRouter(prefix="/odds", tags=["odds"])


@router.get("/{game_id}")
async def get_odds(
    game_id: str, market: str | None = None, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Latest snapshot per (bookmaker, market, outcome) for a game - not the
    full append-only history (constraint: odds_snapshots is immutable and
    grows without bound; a live-odds view wants "now", not every tick)."""
    conditions = [OddsSnapshot.game_id == game_id]
    if market:
        conditions.append(OddsSnapshot.market == market)

    result = await db.execute(
        select(OddsSnapshot).where(*conditions).order_by(OddsSnapshot.captured_at.desc())
    )
    latest: dict[tuple[str, str, str], OddsSnapshot] = {}
    for snap in result.scalars().all():
        key = (snap.bookmaker, snap.market, snap.outcome)
        if key not in latest:
            latest[key] = snap
    return [row_to_dict(s) for s in latest.values()]


@router.get("/{game_id}/best")
async def get_best_odds(
    game_id: str, market: str = "h2h", db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Best (highest American price = most bettor-favourable) current price
    per outcome across every book - the number a "shop for the best line"
    view actually wants."""
    result = await db.execute(
        select(OddsSnapshot)
        .where(OddsSnapshot.game_id == game_id, OddsSnapshot.market == market)
        .order_by(OddsSnapshot.captured_at.desc())
    )
    latest_by_book: dict[tuple[str, str], OddsSnapshot] = {}
    for snap in result.scalars().all():
        key = (snap.bookmaker, snap.outcome)
        if key not in latest_by_book:
            latest_by_book[key] = snap

    best_by_outcome: dict[str, OddsSnapshot] = {}
    for (_book, outcome), snap in latest_by_book.items():
        if snap.price_american is None:
            continue
        current = best_by_outcome.get(outcome)
        if current is None or snap.price_american > (current.price_american or -10_000):
            best_by_outcome[outcome] = snap

    return [row_to_dict(s) for s in best_by_outcome.values()]
