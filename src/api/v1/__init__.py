"""Versioned Sports application API."""

from fastapi import APIRouter

from .schemas import (
    FavoritesResponse,
    GamesResponse,
    ModelHealth,
    OverviewResponse,
    PaperPositionsResponse,
    PlayerOddsResponse,
    TeamOddsResponse,
)

router = APIRouter(prefix="/api/v1", tags=["sports-v1"])


@router.get("/overview", response_model=OverviewResponse)
async def overview() -> OverviewResponse:
    """Return a safe empty overview until the snapshot pipeline is connected."""

    return OverviewResponse(
        qualified=[],
        watchlist=[],
        no_bet=[],
        freshness=None,
        model_health=None,
    )


@router.get("/team-odds", response_model=TeamOddsResponse)
async def team_odds() -> TeamOddsResponse:
    return TeamOddsResponse()


@router.get("/player-odds", response_model=PlayerOddsResponse)
async def player_odds() -> PlayerOddsResponse:
    return PlayerOddsResponse()


@router.get("/games", response_model=GamesResponse)
async def games() -> GamesResponse:
    return GamesResponse()


@router.get("/favorites", response_model=FavoritesResponse)
async def favorites() -> FavoritesResponse:
    return FavoritesResponse()


@router.get("/model-health", response_model=ModelHealth | None)
async def model_health() -> ModelHealth | None:
    return None


@router.get("/paper-positions", response_model=PaperPositionsResponse)
async def paper_positions() -> PaperPositionsResponse:
    return PaperPositionsResponse()
