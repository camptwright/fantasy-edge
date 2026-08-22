"""The API key must never leak into a persisted error message.

httpx.HTTPStatusError's str() embeds the full request URL, including the
apiKey query parameter The Odds API requires. If that message reached
IngestionRun.detail unchanged on a failed request (a bad/rotated key, rate
limiting, a transient 5xx), the live production credential would sit in
plaintext inside an ordinary application table with no secret protection.
Found by an automated security scan, not by the original implementation or
its review - this test is what would have caught it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import httpx
import pytest
from sqlalchemy import select

from config.settings import get_settings
from src.ingest.theodds import poll_team_markets
from src.models.governance import IngestionRun


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


async def test_failed_request_never_leaks_the_api_key_into_run_detail(db, redis):
    settings = get_settings()
    assert settings.odds_api_key, "test requires a real ODDS_API_KEY in .env"

    fake_request = httpx.Request(
        "GET",
        f"{settings.odds_api_base_url}/sports/americanfootball_nfl/odds",
        params={"apiKey": settings.odds_api_key, "regions": "us"},
    )
    fake_response = httpx.Response(401, request=fake_request, json={"message": "bad key"})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.ingest.theodds.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError) as exc_info:
            await poll_team_markets(db, redis)

    assert settings.odds_api_key not in str(exc_info.value)

    run = await db.scalar(
        select(IngestionRun)
        .where(IngestionRun.source == "theodds")
        .order_by(IngestionRun.started_at.desc())
    )
    assert run is not None
    assert run.status == "failed"
    assert run.detail is not None
    assert settings.odds_api_key not in run.detail
    assert run.detail == "RuntimeError: Odds API request failed: 401"
