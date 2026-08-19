from datetime import UTC, datetime, timedelta

from src.api.v1.schemas import MarketStatus, SourceRef
from src.services.assessments import assess_market


def source(observed_at: datetime) -> list[SourceRef]:
    return [SourceRef(provider="test", snapshot_id="s1", observed_at=observed_at)]


def test_uncalibrated_market_never_publishes_numeric_edge():
    now = datetime.now(UTC)
    result = assess_market(
        assessment_id="a1", sport="nfl", league="nfl", event_id="e1", market="h2h", selection="Home",
        probability=0.6, fair_price_american=-150, edge_percent=4.0, estimated_value_percent=3.5,
        sources=source(now), model_version="v1", calibrated=False, coverage_complete=True, now=now,
    )
    assert result.status is MarketStatus.uncalibrated
    assert result.edge_percent is None


def test_stale_source_is_explicit_no_bet():
    now = datetime.now(UTC)
    result = assess_market(
        assessment_id="a1", sport="nfl", league="nfl", event_id="e1", market="h2h", selection="Home",
        probability=0.6, fair_price_american=-150, edge_percent=4.0, estimated_value_percent=3.5,
        sources=source(now - timedelta(hours=1)), model_version="v1", calibrated=True, coverage_complete=True, now=now,
    )
    assert result.status is MarketStatus.stale
