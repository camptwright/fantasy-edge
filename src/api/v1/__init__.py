"""Versioned Sports application API."""

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import (
    AssistantStatus,
    FavoritesResponse,
    Favorite,
    FavoritesUpdateRequest,
    GamesResponse,
    GameDetailResponse,
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
from src.data.providers.espn_api import get_nfl_game_odds
from config.settings import all_sports, get_settings
from src.models.orm import Game, PlayerPropLine
from src.models.sports import Favorite as FavoriteRow
from src.models.sports import MarketAssessment as MarketAssessmentRow
from src.models.orm import OddsSnapshot
from src.services.model_health import calibration_state
from src.utils.odds_math import probability_to_american
import math

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
        freshness=await _freshness(db),
        model_health=await _model_health(db),
    )


@router.get("/team-odds", response_model=TeamOddsResponse)
async def team_odds(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> TeamOddsResponse:
    return TeamOddsResponse(items=await _market_rows(db, sport=sport, player=False))


@router.get("/nfl-predictions")
async def nfl_predictions(db: AsyncSession = Depends(get_db)) -> dict:
    """NFL-only board joining ESPN game markets to our model evidence.

    ESPN is the secondary game-market source here. A line is never presented
    as a model pick unless a calibrated assessment exists for its event;
    player lines remain explicitly pending until the nflverse batch artifact
    has a complete player/game join.
    """
    try:
        games_result = await db.execute(
            select(Game).where(Game.sport == "nfl", Game.status.in_(("scheduled", "live")))
        )
        games = {str(g.espn_event_id): g for g in games_result.scalars().all() if g.espn_event_id}
        assessments_result = await db.execute(
            select(MarketAssessmentRow).where(MarketAssessmentRow.sport == "nfl")
        )
        assessments = list(assessments_result.scalars().all())
        props_result = await db.execute(
            select(PlayerPropLine).where(PlayerPropLine.sport == "nfl").order_by(PlayerPropLine.captured_at.desc()).limit(300)
        )
        props = list(props_result.scalars().all())
        final_result = await db.execute(
            select(Game).where(Game.sport == "nfl", Game.status == "final", Game.home_score.is_not(None), Game.away_score.is_not(None)).limit(2000)
        )
        finals = list(final_result.scalars().all())
    except SQLAlchemyError:
        return {"sport": "nfl", "status": "unavailable", "team_lines": [], "player_lines": []}

    team_lines: list[dict] = []
    def _team_context(game: Game) -> tuple[float, float, float, float]:
        home_for, home_against, away_for, away_against = [], [], [], []
        for final in finals:
            if final.home_team_name == game.home_team_name:
                home_for.append(final.home_score)
                home_against.append(final.away_score)
            if final.away_team_name == game.home_team_name:
                home_for.append(final.away_score)
                home_against.append(final.home_score)
            if final.home_team_name == game.away_team_name:
                away_for.append(final.home_score)
                away_against.append(final.away_score)
            if final.away_team_name == game.away_team_name:
                away_for.append(final.away_score)
                away_against.append(final.home_score)

        def avg(values: list[int], fallback: float) -> float:
            return sum(values) / len(values) if values else fallback
        home_exp = (avg(home_for, 22.5) + avg(away_against, 22.5)) / 2 + 1.5
        away_exp = (avg(away_for, 22.5) + avg(home_against, 22.5)) / 2
        margins = [f.home_score - f.away_score for f in finals]
        totals = [f.home_score + f.away_score for f in finals]
        margin_sd = max(7.0, (sum((x - avg(margins, 0)) ** 2 for x in margins) / max(1, len(margins))) ** 0.5)
        total_sd = max(10.0, (sum((x - avg(totals, 44.0)) ** 2 for x in totals) / max(1, len(totals))) ** 0.5)
        return home_exp, away_exp, margin_sd, total_sd
    try:
        espn_lines = await get_nfl_game_odds()
    except Exception:
        espn_lines = []
    for line in espn_lines:
        game = games.get(line["event_id"])
        if game is None:
            continue
        matching = [a for a in assessments if str(a.event_id) == str(game.id)]
        # h2h is the only calibrated team probability currently published.
        # Never reuse a win probability for a spread or total line.
        target = game.home_team_name if line["selection"] == "home" else game.away_team_name
        model = next((a for a in matching if line["market"] == "moneyline" and a.market == "h2h" and a.selection == target), None)
        home_exp, away_exp, margin_sd, total_sd = _team_context(game)
        projection = None
        model_probability = model.probability if model else None
        if line["market"] == "spread" and line["line"] is not None:
            projection = round(home_exp - away_exp, 2)
            model_probability = round(0.5 * math.erfc((line["line"] - projection) / (margin_sd * math.sqrt(2))), 4)
        elif line["market"] == "total" and line["line"] is not None:
            projection = round(home_exp + away_exp, 2)
            model_probability = round(0.5 * math.erfc((line["line"] - projection) / (total_sd * math.sqrt(2))), 4)
        team_lines.append({
            **line,
            "game_id": str(game.id),
            "matchup": f"{game.away_team_name} @ {game.home_team_name}",
            "model_probability": model_probability,
            "model_projection": projection,
            "fair_price_american": probability_to_american(model_probability) if model_probability is not None else None,
            "model_version": model.model_version if model else None,
            "confidence": "calibrated" if model and model.probability is not None else None,
            "status": model.status if model else "uncalibrated",
            "status_reason": None if model else ("NFL baseline projection priced this line; spread/total market calibration is still pending." if model_probability is not None else "No calibrated NFL assessment is linked to this ESPN line."),
        })

    player_lines = [{
        "id": str(prop.id), "player_name": prop.player_name, "stat_type": prop.stat_type,
        "line": prop.line, "over_price_american": prop.over_price_american,
        "under_price_american": prop.under_price_american, "source": prop.source,
        "captured_at": prop.captured_at, "game_id": str(prop.game_id) if prop.game_id else None,
        "model_projection": None, "model_probability": None, "confidence": None,
        "status": "uncalibrated",
        "status_reason": "nflreadpy player artifact is not complete for this player/game join yet.",
    } for prop in props]
    return {"sport": "nfl", "status": "ready" if team_lines or player_lines else "no_coverage",
            "team_lines": team_lines, "player_lines": player_lines}


@router.get("/player-odds", response_model=PlayerOddsResponse)
async def player_odds(
    sport: str | None = Query(default=None),
    source: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> PlayerOddsResponse:
    return PlayerOddsResponse(items=await _market_rows(db, sport=sport, player=True, source=source))


@router.get("/games", response_model=GamesResponse)
async def games(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> GamesResponse:
    try:
        now = datetime.now(UTC)
        window_end = now + timedelta(days=7)
        query = (
            select(Game)
            .where(
                Game.status.in_(("scheduled", "live")),
                or_(Game.game_time.is_(None), Game.game_time.between(now, window_end)),
            )
            .order_by(Game.game_time.asc().nulls_last())
            .limit(500)
        )
        if sport:
            query = query.where(Game.sport == sport)
        result = await db.execute(query)
    except SQLAlchemyError:
        return GamesResponse()
    return GamesResponse(items=[GameSummary(id=str(row.id), sport=row.sport, league=row.sport, start_time=row.game_time, home_team=row.home_team_name, away_team=row.away_team_name, status=row.status) for row in result.scalars().all()])


@router.get("/games/{game_id}", response_model=GameDetailResponse)
async def game_detail(game_id: str, db: AsyncSession = Depends(get_db)) -> GameDetailResponse:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    summary = GameSummary(
        id=str(game.id), sport=game.sport, league=game.sport, start_time=game.game_time,
        home_team=game.home_team_name, away_team=game.away_team_name, status=game.status,
    )
    return GameDetailResponse(
        game=summary,
        team_lines=await _market_rows(db, sport=game.sport, player=False, game_id=game.id),
        player_props=await _market_rows(db, sport=game.sport, player=True, game_id=game.id),
    )


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
async def model_health(db: AsyncSession = Depends(get_db)) -> ModelHealth | None:
    return await _model_health(db)


@router.get("/assistant-status", response_model=AssistantStatus)
async def assistant_status() -> AssistantStatus:
    """Expose the live Fantasy assistant path without exposing secrets.

    Adjutant itself remains private to CT110. Fantasy Edge's assistant path is
    the shared LiteLLM gateway, which applies the same Hermes -> Mac -> cloud
    routing policy without requiring CT100 to publish Adjutant's port.
    """
    settings = get_settings()
    if not settings.litellm_base_url or not settings.litellm_api_key:
        return AssistantStatus(
            active=False,
            model_alias=settings.fantasy_model_alias,
            service="litellm",
            detail="LiteLLM gateway is not configured",
        )

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            gateway_base = settings.litellm_base_url.rstrip("/").removesuffix("/v1")
            litellm = await client.get(f"{gateway_base}/health/liveliness")
        if litellm.status_code == 200:
            return AssistantStatus(
                active=True,
                model_alias=settings.fantasy_model_alias,
                service="litellm",
                detail="LiteLLM gateway is reachable; local-first fallback is active",
            )
        detail = f"LiteLLM {litellm.status_code}"
    except httpx.HTTPError:
        detail = "LiteLLM gateway is unreachable"
    return AssistantStatus(
        active=False,
        model_alias=settings.fantasy_model_alias,
        service="litellm",
        detail=detail,
    )


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


async def _freshness(db: AsyncSession):
    try:
        newest = (await db.execute(select(func.max(OddsSnapshot.captured_at)))).scalar_one()
    except SQLAlchemyError:
        return None
    if newest is None:
        return None
    now = datetime.now(UTC)
    age = max(0, int((now - newest).total_seconds()))
    from .schemas import Freshness

    return Freshness(newest_observation=newest, age_seconds=age, status="current" if age <= 900 else "stale")


async def _model_health(db: AsyncSession) -> ModelHealth:
    """Expose evidence, including unavailable/degraded states, never a guess."""
    calibration_by_sport = {sport: calibration_state(sport) for sport in all_sports()}
    try:
        newest = (await db.execute(select(func.max(OddsSnapshot.captured_at)))).scalar_one()
    except SQLAlchemyError:
        newest = None
    now = datetime.now(UTC)
    fresh = newest is not None and (now - newest).total_seconds() <= 900
    passing = [state for state in calibration_by_sport.values() if state.calibrated]
    latest = next((state for state in passing if state.model_version), None)
    # Model health answers whether a calibrated artifact is safe to price.
    # Feed freshness is reported independently in coverage: an exhausted or
    # paused odds provider must not make a valid model appear uncalibrated.
    status = "healthy" if latest else "degraded" if newest or any(state.model_version for state in calibration_by_sport.values()) else "unavailable"
    return ModelHealth(
        model_version=latest.model_version if latest else "untrained",
        coverage={"odds_feed": fresh, "calibrated_model": bool(passing)},
        calibration={sport: state.oof_brier for sport, state in calibration_by_sport.items()},
        last_successful_ingest=newest,
        status=status,
    )


async def _market_rows(db: AsyncSession, *, sport: str | None, player: bool, game_id=None, source: str | None = None) -> list[MarketAssessment]:
    if player:
        return await _player_prop_rows(db, sport=sport, game_id=game_id, source=source)
    try:
        query = select(MarketAssessmentRow).order_by(MarketAssessmentRow.assessed_at.desc()).limit(200)
        if sport:
            query = query.where(MarketAssessmentRow.sport == sport)
        if game_id:
            query = query.where(MarketAssessmentRow.event_id == game_id)
        result = await db.execute(query)
    except SQLAlchemyError:
        return []
    # Player/team market classification remains explicit until canonical
    # participant links are populated; never guess from display text.
    rows = [row for row in result.scalars().all() if (row.market.startswith("player_") == player)]
    return [_assessment(row) for row in rows]


async def _player_prop_rows(db: AsyncSession, *, sport: str | None, game_id=None, source: str | None = None) -> list[MarketAssessment]:
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
    if game_id:
        query = query.where(PlayerPropLine.game_id == game_id)
    if source:
        query = query.where(PlayerPropLine.source == source)
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
                    player_name=prop.player_name,
                    side=side,
                    assessed_at=prop.captured_at,
                )
            )
    return rows
