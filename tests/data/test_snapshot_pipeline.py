from datetime import UTC, datetime

from src.data.providers.base import NormalizedMarket


def test_normalized_market_requires_provider_and_event_identity():
    market = NormalizedMarket(
        provider="theoddsapi",
        external_event_id="event-1",
        sport="nfl",
        market="h2h",
        outcome="Home",
        bookmaker="consensus",
        captured_at=datetime.now(UTC),
    )
    assert market.provider == "theoddsapi"
    assert market.external_event_id == "event-1"
