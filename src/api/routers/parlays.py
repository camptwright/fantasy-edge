"""CONSTRAINT #12: parlay generation uses the shared LiteLLM gateway and must work from
prop edges alone - it must NEVER require `bet_signals` to be non-empty,
since signals only exist after odds polling has succeeded (and odds polling
needs `ODDS_API_KEY`, which is a separate, independently-configurable piece
of this system - see CLAUDE.md "Known gaps"). This router only ever reads
from `player_prop_lines`, never `bet_signals`, to keep that decoupling real
rather than aspirational.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI, OpenAIError
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


def _build_prompt(props: list[PlayerPropLine], num_legs: int) -> str:
    lines = []
    for p in props:
        lines.append(
            f"- {p.player_name} | {p.stat_type} | line {p.line} | "
            f"over {p.over_price_american} / under {p.under_price_american} | source {p.source}"
        )
    return (
        f"You are picking a {num_legs}-leg player-prop parlay from the candidates below. "
        "Prefer diversification across players and stat types over stacking the same "
        "player twice. Respond ONLY with JSON matching this shape: "
        '{"title": str, "rationale": str, '
        '"legs": [{"player_name": str, "stat_type": str, "selection": "over"|"under", '
        '"line": number}]}\n\nCandidates:\n' + "\n".join(lines)
    )


@router.post("/generate")
async def generate_parlay(
    request: GenerateParlayRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    settings = get_settings()
    if not settings.litellm_base_url or not settings.litellm_api_key:
        raise HTTPException(
            status_code=503,
            detail="LiteLLM is not configured - parlay generation is unavailable",
        )

    props = await _candidate_props(db, request.sport)
    if len(props) < 2:
        raise HTTPException(
            status_code=422,
            detail="not enough current prop lines to build a parlay - PropsAgent may not "
            "have run yet",
        )

    num_legs = max(2, min(request.num_legs, MAX_LEGS, len(props)))
    prompt = _build_prompt(props, num_legs)

    # LiteLLM exposes an OpenAI-compatible API. The `worker` alias resolves in
    # order: Hermes/Ollama on the gaming PC -> Ollama on the Mac mini -> cloud.
    client = AsyncOpenAI(
        base_url=settings.litellm_base_url.rstrip("/") + "/",
        api_key=settings.litellm_api_key,
    )
    try:
        response = await client.chat.completions.create(
            model=settings.fantasy_model_alias,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
    except OpenAIError as exc:
        log.exception("parlay_generate.litellm_failed")
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    try:
        parsed = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502, detail="LLM returned an unparseable response"
        ) from exc

    props_by_key = {(p.normalized_name, p.stat_type): p for p in props}

    parlay = Parlay(
        sport=request.sport,
        title=parsed.get("title"),
        rationale=parsed.get("rationale"),
        generator=settings.fantasy_model_alias,
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
