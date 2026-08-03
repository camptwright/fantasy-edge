from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.serializers import row_to_dict
from src.data.cache.db_client import get_db
from src.models.orm import BetSignal, Game

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
async def list_signals(
    sport: str | None = None,
    min_ev: float = Query(default=0.0),
    tier: str | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """EV-sorted (highest first) with game context inlined - the dashboard's
    Signals view is built around "biggest edges first", not signal id or
    creation time."""
    conditions = [BetSignal.ev_percent >= min_ev]
    if sport:
        conditions.append(BetSignal.sport == sport)
    if tier:
        conditions.append(BetSignal.tier == tier)

    result = await db.execute(
        select(BetSignal, Game)
        .join(Game, Game.id == BetSignal.game_id)
        .where(*conditions)
        .order_by(BetSignal.ev_percent.desc())
        .limit(limit)
    )

    rows = []
    for signal, game in result.all():
        row = row_to_dict(signal)
        row["matchup"] = f"{game.away_team_name} @ {game.home_team_name}"
        row["game_time"] = game.game_time
        row["game_status"] = game.status
        rows.append(row)
    return rows


@router.get("/{signal_id}")
async def get_signal(signal_id: str, db: AsyncSession = Depends(get_db)) -> dict | None:
    signal = await db.get(BetSignal, signal_id)
    return row_to_dict(signal) if signal else None
