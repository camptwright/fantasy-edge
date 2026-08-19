"""Deterministic API fixtures for tests and local UI development only."""

from datetime import UTC, datetime

from .schemas import MarketAssessment, MarketStatus


def empty_assessment(status: MarketStatus, reason: str) -> MarketAssessment:
    return MarketAssessment(
        id="fixture-assessment",
        sport="nfl",
        league="nfl",
        event_id="fixture-event",
        market="moneyline",
        selection="Unavailable",
        status=status,
        status_reason=reason,
        assessed_at=datetime.now(UTC),
    )
