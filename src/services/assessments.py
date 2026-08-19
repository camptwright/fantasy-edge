"""Safety gates around publishing a market assessment.

This service does not implement a model. It accepts a model result and a
source-qualified consensus result, then decides whether the result is safe to
publish as qualified or must remain an explicit no-bet state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.api.v1.schemas import MarketAssessment, MarketStatus, SourceRef


def assess_market(
    *,
    assessment_id: str,
    sport: str,
    league: str,
    event_id: str,
    market: str,
    selection: str,
    probability: float | None,
    fair_price_american: int | None,
    edge_percent: float | None,
    estimated_value_percent: float | None,
    sources: list[SourceRef],
    model_version: str | None,
    calibrated: bool,
    coverage_complete: bool,
    observed_at: datetime | None = None,
    now: datetime | None = None,
    max_age_seconds: int = 900,
) -> MarketAssessment:
    """Build one assessment, withholding numbers when a gate is not met."""

    assessed_at = now or datetime.now(UTC)
    status = MarketStatus.qualified
    reason: str | None = None
    if not sources:
        status, reason = MarketStatus.coverage_incomplete, "No source snapshots support this market."
    elif not coverage_complete:
        status, reason = MarketStatus.coverage_incomplete, "Required event or participant context is incomplete."
    elif not calibrated:
        status, reason = MarketStatus.uncalibrated, "The model has no passing calibration record for this market."
    elif observed_at is None or (assessed_at - observed_at).total_seconds() > max_age_seconds:
        status, reason = MarketStatus.stale, "The newest source observation is outside the freshness window."
    elif probability is None or fair_price_american is None:
        status, reason = MarketStatus.unsupported_market, "This market does not have enough model output to price."

    publish_values = status is MarketStatus.qualified
    return MarketAssessment(
        id=assessment_id,
        sport=sport,
        league=league,
        event_id=event_id,
        market=market,
        selection=selection,
        status=status,
        status_reason=reason,
        probability=probability if publish_values else None,
        fair_price_american=fair_price_american if publish_values else None,
        edge_percent=edge_percent if publish_values else None,
        estimated_value_percent=estimated_value_percent if publish_values else None,
        model_version=model_version if publish_values else None,
        calibration_label="passing" if publish_values else None,
        sources=sources,
        assessed_at=assessed_at,
    )
