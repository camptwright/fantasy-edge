from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.cache.db_client import get_db
from src.models.orm import PowerRanking, Team

router = APIRouter(prefix="/rankings", tags=["rankings"])


@router.get("/{sport}")
async def get_rankings(sport: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Latest ELO rating per team - `power_rankings.as_of` lets backtests
    read a point-in-time snapshot, but the live rankings view always wants
    the newest row per team, hence DISTINCT ON here too."""
    stmt = (
        select(PowerRanking, Team.name)
        .join(Team, Team.id == PowerRanking.team_id)
        .distinct(PowerRanking.team_id)
        .where(PowerRanking.sport == sport)
        .order_by(PowerRanking.team_id, PowerRanking.as_of.desc())
    )
    result = await db.execute(stmt)
    rows = [
        {
            "team_id": str(ranking.team_id),
            "team_name": name,
            "elo_rating": ranking.elo_rating,
            "as_of": ranking.as_of,
        }
        for ranking, name in result.all()
    ]
    rows.sort(key=lambda r: r["elo_rating"], reverse=True)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
