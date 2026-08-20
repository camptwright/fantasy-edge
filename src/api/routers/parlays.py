"""CONSTRAINT #12: parlay generation uses the shared LiteLLM gateway and must work from
prop edges alone - it must NEVER require `bet_signals` to be non-empty,
since signals only exist after odds polling has succeeded (and odds polling
needs `ODDS_API_KEY`, which is a separate, independently-configurable piece
of this system - see CLAUDE.md "Known gaps"). This router only ever reads
from `player_prop_lines`, never `bet_signals`, to keep that decoupling real
rather than aspirational.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.api.serializers import row_to_dict
from src.data.cache.db_client import get_db
from src.models.orm import Parlay, ParlayLeg, PlayerPropLine
from src.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/parlays", tags=["parlays"])

MAX_CANDIDATE_PROPS = 20
MAX_LEGS = 4


class GenerateParlayRequest(BaseModel):
    sport: str | None = None
    num_legs: int = 3


async def _candidate_props(db: AsyncSession, sport: str | None) -> list[PlayerPropLine]:
    """Prop rows to hand the model, ranked by whatever edge signal exists.

    Prefers `edge_percent` (populated once a projections pipeline computes
    it - not required for this endpoint to function). Falls back to the
    same cross-source line-spread ranking as `/props/best` when no rows
    have a computed edge yet, so this endpoint works from day one rather
    than depending on a projection engine being wired up first - the same
    "don't require an upstream step that may not exist yet" principle
    driving the bet_signals decoupling above.
    """
    conditions = []
    if sport:
        conditions.append(PlayerPropLine.sport == sport)

    stmt = (
        select(PlayerPropLine)
        .distinct(PlayerPropLine.player_name, PlayerPropLine.stat_type, PlayerPropLine.source)
        .order_by(
            PlayerPropLine.player_name,
            PlayerPropLine.stat_type,
            PlayerPropLine.source,
            PlayerPropLine.captured_at.desc(),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    with_edge = [r for r in rows if r.edge_percent is not None]
    ranked = (
        sorted(with_edge, key=lambda r: abs(r.edge_percent), reverse=True)
        if with_edge
        else rows
    )
    return ranked[:MAX_CANDIDATE_PROPS]


@router.post("/generate")
async def generate_parlay(
    request: GenerateParlayRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    settings = get_settings()
    if not settings.adjutant_api_url or not settings.fantasy_parlay_token:
        raise HTTPException(
            status_code=503,
            detail="Adjutant parlay reasoning is not configured",
        )

    props = await _candidate_props(db, request.sport)
    if len(props) < 2:
        raise HTTPException(
            status_code=422,
            detail="not enough current prop lines to build a parlay - PropsAgent may not "
            "have run yet",
        )

    num_legs = max(2, min(request.num_legs, MAX_LEGS, len(props)))
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.adjutant_api_url.rstrip('/')}/sports/parlays/generate",
                headers={"Authorization": f"Bearer {settings.fantasy_parlay_token}"},
                json={
                    "num_legs": num_legs,
                    "candidates": [
                        {"player_name": prop.player_name, "stat_type": prop.stat_type, "line": prop.line,
                         "over_price_american": prop.over_price_american, "under_price_american": prop.under_price_american,
                         "source": prop.source}
                        for prop in props
                    ],
                },
            )
            response.raise_for_status()
            parsed = response.json()
    except httpx.HTTPError as exc:
        log.exception("parlay_generate.adjutant_failed")
        raise HTTPException(status_code=502, detail="Adjutant parlay reasoning failed") from exc

    props_by_key = {(p.normalized_name, p.stat_type): p for p in props}

    parlay = Parlay(
        sport=request.sport,
        title=parsed.get("title"),
        rationale=parsed.get("rationale"),
        generator=f"adjutant:{parsed.get('model_alias', settings.fantasy_model_alias)}",
    )
    db.add(parlay)
    await db.flush()

    from src.utils.normalize import normalize_player_name, normalize_stat_type

    for leg in parsed.get("legs", [])[:MAX_LEGS]:
        key = (
            normalize_player_name(leg.get("player_name", "")),
            normalize_stat_type(leg.get("stat_type", "")),
        )
        prop = props_by_key.get(key)
        if prop is None:
            continue
        db.add(
            ParlayLeg(
                parlay_id=parlay.id,
                prop_line_id=prop.id if prop else None,
                description=f"{leg.get('player_name')} {leg.get('selection')} "
                f"{leg.get('line')} {leg.get('stat_type')}",
                selection=leg.get("selection"),
            )
        )

    await db.commit()
    await db.refresh(parlay)
    return row_to_dict(parlay)


@router.get("")
async def list_parlays(
    sport: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    conditions = [Parlay.sport == sport] if sport else []
    result = await db.execute(
        select(Parlay).where(*conditions).order_by(Parlay.created_at.desc()).limit(limit)
    )
    return [row_to_dict(p) for p in result.scalars().all()]
