"""CONSTRAINT #9: default status=scheduled, game_date >= NOW() strictly
future, 7-day forward window - never default to dumping all history.

CONSTRAINT #2: `game_time` is nullable (providers publish fixtures before a
kickoff time exists), so the future-window filter must be
`or_(Game.game_time.is_(None), Game.game_time BETWEEN now AND now+7d)` -
a plain `Game.game_time >= now` silently drops every fixture without a
known kickoff, which is exactly the bug this constraint documents.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import all_sports
from src.api.serializers import row_to_dict
from src.data.cache.db_client import get_db
from src.models.orm import Game

router = APIRouter(prefix="/games", tags=["games"])


@router.get("")
async def list_games(
    sport: str | None = Query(default=None),
    status: str = Query(default="scheduled"),
    days: int = Query(default=7, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    if sport is not None and sport not in all_sports():
        return []

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=days)

    conditions = [Game.status == status]
    if sport is not None:
        conditions.append(Game.sport == sport)
    if status == "scheduled":
        conditions.append(
            or_(
                Game.game_time.is_(None),
                Game.game_time.between(now, window_end),
            )
        )

    result = await db.execute(
        select(Game).where(*conditions).order_by(Game.game_time.asc().nulls_last())
    )
    return [row_to_dict(g) for g in result.scalars().all()]


@router.get("/{game_id}")
async def get_game(game_id: str, db: AsyncSession = Depends(get_db)) -> dict | None:
    game = await db.get(Game, game_id)
    return row_to_dict(game) if game else None
