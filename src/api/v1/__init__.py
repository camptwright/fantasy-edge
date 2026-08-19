"""Versioned Sports application API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import (
    FavoritesResponse,
    FavoritesUpdateRequest,
    GamesResponse,
    GameSummary,
    MarketAssessment,
    MarketStatus,
    ModelHealth,
    OverviewResponse,
    PaperPositionsResponse,
    ParlayAssessmentRequest,
    ParlayAssessmentResponse,
    PlayerOddsResponse,
    SourceRef,
    TeamOddsResponse,
)
from src.data.cache.db_client import get_db
from src.models.orm import Game, PlayerPropLine
from src.models.sports import Favorite as FavoriteRow
from src.models.sports import MarketAssessment as MarketAssessmentRow

router = APIRouter(prefix="/api/v1", tags=["sports-v1"])


@router.get("/overview", response_model=OverviewResponse)
async def overview(db: AsyncSession = Depends(get_db)) -> OverviewResponse:
    """Return the current board, failing closed while a migration is pending."""
    try:
        result = await db.execute(select(MarketAssessmentRow).order_by(MarketAssessmentRow.assessed_at.desc()).limit(100))
        rows = list(result.scalars().all())
    except SQLAlchemyError:
        return OverviewResponse(qualified=[], watchlist=[], no_bet=[], freshness=None, model_health=None)
    assessments = [_assessment(row) for row in rows]
    return OverviewResponse(
        qualified=[row for row in assessments if row.status is MarketStatus.qualified],
        watchlist=[row for row in assessments if row.status in {MarketStatus.stale, MarketStatus.coverage_incomplete}],
        no_bet=[row for row in assessments if row.status not in {MarketStatus.qualified, MarketStatus.stale, MarketStatus.coverage_incomplete}],
        freshness=None,
        model_health=None,
    )


@router.get("/team-odds", response_model=TeamOddsResponse)
async def team_odds(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> TeamOddsResponse:
    return TeamOddsResponse(items=await _market_rows(db, sport=sport, player=False))


@router.get("/player-odds", response_model=PlayerOddsResponse)
async def player_odds(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> PlayerOddsResponse:
    return PlayerOddsResponse(items=await _market_rows(db, sport=sport, player=True))


@router.get("/games", response_model=GamesResponse)
async def games(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> GamesResponse:
    try:
        query = select(Game).where(Game.status == "scheduled").order_by(Game.game_time.asc().nulls_last()).limit(100)
        if sport:
            query = query.where(Game.sport == sport)
        result = await db.execute(query)
    except SQLAlchemyError:
        return GamesResponse()
    return GamesResponse(items=[GameSummary(id=str(row.id), sport=row.sport, league=row.sport, start_time=row.game_time, home_team=row.home_team_name, away_team=row.away_team_name, status=row.status) for row in result.scalars().all()])


@router.get("/favorites", response_model=FavoritesResponse)
async def favorites(db: AsyncSession = Depends(get_db)) -> FavoritesResponse:
    try:
        result = await db.execute(select(FavoriteRow).order_by(FavoriteRow.created_at.desc()))
    except SQLAlchemyError:
        return FavoritesResponse()
    return FavoritesResponse(items=[Favorite(id=str(row.id), kind=row.kind, canonical_id=str(row.canonical_id), display_name=row.display_name, sport=row.sport) for row in result.scalars().all()])


@router.put("/favorites", response_model=FavoritesResponse)
async def replace_favorites(request: FavoritesUpdateRequest, db: AsyncSession = Depends(get_db)) -> FavoritesResponse:
    """Replace the single shared homelab favorite list."""
    import uuid

    await db.execute(FavoriteRow.__table__.delete())
    rows = []
    for item in request.items:
        try:
            canonical_id = uuid.UUID(item.canonical_id)
        except ValueError as exc:
            raise ValueError(f"favorite canonical_id is not a UUID: {item.canonical_id}") from exc
        row = FavoriteRow(kind=item.kind, canonical_id=canonical_id, display_name=item.display_name, sport=item.sport)
        db.add(row)
        rows.append(row)
    await db.commit()
    return FavoritesResponse(items=[Favorite(id=str(row.id), kind=row.kind, canonical_id=str(row.canonical_id), display_name=row.display_name, sport=row.sport) for row in rows])


@router.get("/model-health", response_model=ModelHealth | None)
async def model_health() -> ModelHealth | None:
    return None


@router.get("/paper-positions", response_model=PaperPositionsResponse)
async def paper_positions() -> PaperPositionsResponse:
    return PaperPositionsResponse()


@router.post("/parlays/assess", response_model=ParlayAssessmentResponse)
async def assess_parlay(request: ParlayAssessmentRequest, db: AsyncSession = Depends(get_db)) -> ParlayAssessmentResponse:
    """Validate a candidate parlay without placing or saving a wager."""
    from datetime import UTC, datetime

    ids = [leg.assessment_id for leg in request.legs]
    try:
        result = await db.execute(select(MarketAssessmentRow).where(MarketAssessmentRow.id.in_(ids)))
        rows = list(result.scalars().all())
    except SQLAlchemyError:
        rows = []
    by_id = {str(row.id): row for row in rows}
    assessed_at = datetime.now(UTC)
    if len(by_id) != len(set(ids)):
        return ParlayAssessmentResponse(status=MarketStatus.coverage_incomplete, status_reason="One or more legs has no retained assessment.", leg_count=len(request.legs), assessed_at=assessed_at)
    if any(row.status != MarketStatus.qualified.value for row in by_id.values()):
        return ParlayAssessmentResponse(status=MarketStatus.coverage_incomplete, status_reason="Every leg must be qualified at assessment time.", leg_count=len(request.legs), assessed_at=assessed_at)
    if len({str(row.event_id) for row in by_id.values()}) != len(by_id):
        return ParlayAssessmentResponse(status=MarketStatus.cannot_price_correlation, status_reason="Multiple legs share an event and correlation is not modeled.", leg_count=len(request.legs), assessed_at=assessed_at)
    return ParlayAssessmentResponse(status=MarketStatus.cannot_price_correlation, status_reason="Cross-event dependence is not yet modeled for combined pricing.", leg_count=len(request.legs), assessed_at=assessed_at)


def _assessment(row: MarketAssessmentRow) -> MarketAssessment:
    sources = [SourceRef(provider="snapshot", snapshot_id=str(snapshot_id), observed_at=row.assessed_at) for snapshot_id in (row.source_snapshot_ids or [])]
    return MarketAssessment(
        id=str(row.id), sport=row.sport, league=row.league, event_id=str(row.event_id), market=row.market,
        selection=row.selection, status=MarketStatus(row.status), status_reason=row.status_reason,
        probability=row.probability, fair_price_american=row.fair_price_american, edge_percent=row.edge_percent,
        estimated_value_percent=row.estimated_value_percent, model_version=row.model_version,
        calibration_label="passing" if row.status == MarketStatus.qualified.value else None,
        sources=sources, assessed_at=row.assessed_at,
    )


async def _market_rows(db: AsyncSession, *, sport: str | None, player: bool) -> list[MarketAssessment]:
    if player:
        return await _player_prop_rows(db, sport=sport)
    try:
        query = select(MarketAssessmentRow).order_by(MarketAssessmentRow.assessed_at.desc()).limit(200)
        if sport:
            query = query.where(MarketAssessmentRow.sport == sport)
        result = await db.execute(query)
    except SQLAlchemyError:
        return []
    # Player/team market classification remains explicit until canonical
    # participant links are populated; never guess from display text.
    rows = [row for row in result.scalars().all() if (row.market.startswith("player_") == player)]
    return [_assessment(row) for row in rows]


async def _player_prop_rows(db: AsyncSession, *, sport: str | None) -> list[MarketAssessment]:
    """Expose retained provider lines without pretending they are model edges.

    Underdog props are already ingested by the legacy worker. Until player
    identity, event context, and calibration gates are complete, each side is
    deliberately marked ``coverage_incomplete`` and carries no fair price or
    edge. This makes the observed line useful while preserving the no-bet
    safety contract.
    """
    query = (
        select(PlayerPropLine)
        .distinct(PlayerPropLine.player_name, PlayerPropLine.stat_type, PlayerPropLine.source)
        .order_by(
            PlayerPropLine.player_name,
            PlayerPropLine.stat_type,
            PlayerPropLine.source,
            PlayerPropLine.captured_at.desc(),
        )
        .limit(200)
    )
    if sport:
        query = query.where(PlayerPropLine.sport == sport)
    try:
        result = await db.execute(query)
    except SQLAlchemyError:
        return []

    rows: list[MarketAssessment] = []
    for prop in result.scalars().all():
        event_id = str(prop.game_id) if prop.game_id else f"unmatched:{prop.id}"
        for side, price in (("over", prop.over_price_american), ("under", prop.under_price_american)):
            rows.append(
                MarketAssessment(
                    id=f"{prop.id}:{side}",
                    sport=prop.sport,
                    league=prop.sport,
                    event_id=event_id,
                    market=f"player_{prop.stat_type}",
                    selection=f"{prop.player_name} {side.upper()} {prop.line:g}",
                    status=MarketStatus.coverage_incomplete,
                    status_reason="Observed provider line; player/event identity or model calibration is incomplete.",
                    line=prop.line,
                    price_american=price,
                    bookmaker=prop.source,
                    assessed_at=prop.captured_at,
                )
            )
    return rows
