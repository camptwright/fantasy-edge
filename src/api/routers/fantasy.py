"""DFS lineup optimization, projections, and season-long VOR tools.

Scope note: this system has no DraftKings/FanDuel salary feed and no
season-long roster/gamelog provider (nothing in Phase 2 ingests either -
`config/sports.yaml`, the providers, and the constraints never mention
one). `/dfs/optimize`, `/start-sit`, and `/waivers` therefore accept the
player pool/roster in the request body rather than pretending to read it
from a database table that doesn't exist - the dashboard's Fantasy page is
expected to supply that data (pasted from a salary export or the user's
actual league), and this router is the calculation service, not the data
source, for those three. `/projections/{sport}` is the one endpoint that
DOES read from our own data: it derives a lightweight projection straight
from current Underdog lines (constraint #5's `line` value is itself the
market's implied projection for that stat), since PlayerPropLine is real
ingested data and a full boxscore/gamelog history is not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.algorithms.dfs_optimizer import (
    LineupResult,
    PlayerCandidate,
    get_site_rules,
    optimize_lineup,
)
from src.algorithms.value_over_replacement import (
    PlayerValue,
    VorResult,
    calculate_vor,
    start_sit_recommendation,
    waiver_targets,
)
from src.data.cache.db_client import get_db
from src.models.orm import PlayerPropLine

router = APIRouter(prefix="/fantasy", tags=["fantasy"])


# ------------------------------------------------------------- dfs optimize ----


class DfsPlayerInput(BaseModel):
    player_id: str
    name: str
    team: str
    positions: list[str]
    salary: int
    projected_points: float


class DfsOptimizeRequest(BaseModel):
    sport: str
    site: str
    players: list[DfsPlayerInput]
    locked_player_ids: list[str] = []
    excluded_player_ids: list[str] = []


@router.post("/dfs/optimize")
async def optimize_dfs_lineup(request: DfsOptimizeRequest) -> dict:
    try:
        rules = get_site_rules(request.site, request.sport)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    candidates = [
        PlayerCandidate(
            player_id=p.player_id,
            name=p.name,
            team=p.team,
            positions=frozenset(p.positions),
            salary=p.salary,
            projected_points=p.projected_points,
        )
        for p in request.players
    ]

    result: LineupResult = optimize_lineup(
        candidates,
        rules,
        locked_player_ids=frozenset(request.locked_player_ids),
        excluded_player_ids=frozenset(request.excluded_player_ids),
    )
    if not result.feasible:
        raise HTTPException(
            status_code=422,
            detail="no feasible lineup under the given salary cap / roster rules / "
            "lock-exclude constraints",
        )

    return {
        "feasible": result.feasible,
        "total_salary": result.total_salary,
        "salary_cap": rules.salary_cap,
        "total_projected_points": result.total_projected_points,
        "assignments": [a.__dict__ for a in result.assignments],
    }


# ------------------------------------------------------------- projections ----


@router.get("/projections/{sport}")
async def get_projections(sport: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Current Underdog lines as a lightweight per-player projection table -
    see module docstring for why this isn't the full recency-weighted
    projections.py model."""
    stmt = (
        select(PlayerPropLine)
        .distinct(PlayerPropLine.player_name, PlayerPropLine.stat_type, PlayerPropLine.source)
        .where(PlayerPropLine.sport == sport)
        .order_by(
            PlayerPropLine.player_name,
            PlayerPropLine.stat_type,
            PlayerPropLine.source,
            PlayerPropLine.captured_at.desc(),
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "player_name": r.player_name,
            "stat_type": r.stat_type,
            "projected_value": r.line,
            "source": r.source,
            "captured_at": r.captured_at,
        }
        for r in rows
    ]


# ------------------------------------------------------------- start/sit + waivers ----


class VorPlayerInput(BaseModel):
    player_id: str
    name: str
    position: str
    projected_points: float


class StartSitRequest(BaseModel):
    roster: list[VorPlayerInput]
    starters_by_position: dict[str, int]


class WaiversRequest(BaseModel):
    available_players: list[VorPlayerInput]
    rostered_player_ids: list[str]
    limit: int = 20


def _vor_response(results: list[VorResult]) -> list[dict]:
    return [r.__dict__ for r in results]


@router.post("/start-sit")
async def start_sit(request: StartSitRequest) -> dict:
    """A single request-model body, not several bare list/dict params -
    FastAPI only auto-combines multiple body parameters into one JSON object
    when each is keyed by name; a plain JSON array as the whole request body
    (what a client naturally sends for "a roster") only works with exactly
    one body parameter. Verified against the earlier two-bare-params version,
    which curled with a 422 "field required" for a body that was actually
    present, just not shaped the way FastAPI expected.
    """
    values = [
        PlayerValue(p.player_id, p.name, p.position, p.projected_points)
        for p in request.roster
    ]
    vor_results = calculate_vor(values)
    rec = start_sit_recommendation(
        vor_results, starters_by_position=request.starters_by_position
    )
    return {"start": _vor_response(rec["start"]), "sit": _vor_response(rec["sit"])}


@router.post("/waivers")
async def waivers(request: WaiversRequest) -> list[dict]:
    values = [
        PlayerValue(p.player_id, p.name, p.position, p.projected_points)
        for p in request.available_players
    ]
    vor_results = calculate_vor(values)
    targets = waiver_targets(
        set(request.rostered_player_ids), vor_results, limit=request.limit
    )
    return _vor_response(targets)
