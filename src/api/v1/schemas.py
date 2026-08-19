"""Stable API contracts for the standalone Sports workspace.

These schemas deliberately distinguish missing/unsafe data from a qualified
assessment.  A consumer must never infer a recommendation from a nullable
numeric value alone.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketStatus(str, Enum):
    qualified = "qualified"
    stale = "stale"
    coverage_incomplete = "coverage_incomplete"
    uncalibrated = "uncalibrated"
    unsupported_market = "unsupported_market"
    cannot_price_correlation = "cannot_price_correlation"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    snapshot_id: str
    observed_at: datetime


class MarketAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sport: str
    league: str
    event_id: str
    market: str
    selection: str
    status: MarketStatus
    status_reason: str | None = None
    probability: float | None = Field(default=None, ge=0, le=1)
    fair_price_american: int | None = None
    line: float | None = None
    price_american: int | None = None
    bookmaker: str | None = None
    player_name: str | None = None
    side: Literal["over", "under"] | None = None
    edge_percent: float | None = None
    estimated_value_percent: float | None = None
    model_version: str | None = None
    calibration_label: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    assessed_at: datetime


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newest_observation: datetime
    age_seconds: int = Field(ge=0)
    status: Literal["current", "stale", "unavailable"]


class ModelHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str
    coverage: dict[str, bool] = Field(default_factory=dict)
    calibration: dict[str, float | None] = Field(default_factory=dict)
    last_successful_ingest: datetime | None = None
    status: Literal["healthy", "degraded", "unavailable"]


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualified: list[MarketAssessment] = Field(default_factory=list)
    watchlist: list[MarketAssessment] = Field(default_factory=list)
    no_bet: list[MarketAssessment] = Field(default_factory=list)
    freshness: Freshness | None = None
    model_health: ModelHealth | None = None


class TeamOddsResponse(BaseModel):
    items: list[MarketAssessment] = Field(default_factory=list)
    next_cursor: str | None = None


class PlayerOddsResponse(BaseModel):
    items: list[MarketAssessment] = Field(default_factory=list)
    next_cursor: str | None = None


class GameSummary(BaseModel):
    id: str
    sport: str
    league: str
    start_time: datetime | None = None
    home_team: str | None = None
    away_team: str | None = None
    status: str


class GamesResponse(BaseModel):
    items: list[GameSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class GameDetailResponse(BaseModel):
    game: GameSummary
    team_lines: list[MarketAssessment] = Field(default_factory=list)
    player_props: list[MarketAssessment] = Field(default_factory=list)


class Favorite(BaseModel):
    id: str
    kind: Literal["team", "player"]
    canonical_id: str
    display_name: str
    sport: str


class FavoritesResponse(BaseModel):
    items: list[Favorite] = Field(default_factory=list)


class FavoritesUpdateRequest(BaseModel):
    items: list[Favorite] = Field(max_length=100)


class ParlayLeg(BaseModel):
    assessment_id: str
    event_id: str
    market: str
    selection: str


class ParlayAssessmentRequest(BaseModel):
    legs: list[ParlayLeg] = Field(min_length=2, max_length=12)


class ParlayAssessmentResponse(BaseModel):
    status: MarketStatus
    status_reason: str | None = None
    leg_count: int = Field(ge=0)
    combined_probability: float | None = Field(default=None, ge=0, le=1)
    estimated_value_percent: float | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    assessed_at: datetime


class PaperPosition(BaseModel):
    id: str
    assessment_id: str
    assumed_price_american: int
    stake_units: float = Field(gt=0)
    opened_at: datetime
    outcome: Literal["open", "win", "loss", "push", "void"] = "open"


class PaperPositionsResponse(BaseModel):
    items: list[PaperPosition] = Field(default_factory=list)
