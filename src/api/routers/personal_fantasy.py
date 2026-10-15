"""Private decision journal; mount with the production API token dependency."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.client import get_db
from src.services.personal_decisions import create, history, InvalidDecision

router = APIRouter(prefix='/api/v2/personal-fantasy', tags=['personal-fantasy'])


class DecisionInput(BaseModel):
    request_id: UUID
    generated_at: str = Field(max_length=80)
    action: Literal['start', 'pickup', 'trade']
    player_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=30)
    counterparty_player_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=6)
    note: str = Field(default='', max_length=1000)


@router.post('/leagues/{league_id}/decisions')
async def save(league_id: str, request: DecisionInput, db: AsyncSession = Depends(get_db)):
    try:
        return await create(db, league_id, request.model_dump(mode='json'))
    except InvalidDecision as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/leagues/{league_id}/decisions')
async def list_decisions(league_id: str, limit: int = Query(default=50, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    return {'league_id': league_id, 'records': await history(db, league_id, limit=limit)}
