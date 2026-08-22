"""The API key must never leak into a persisted error message.

httpx.HTTPStatusError's str() embeds the full request URL, including the
apiKey query parameter The Odds API requires. If that message reached
IngestionRun.detail unchanged on a failed request (a bad/rotated key, rate
limiting, a transient 5xx), the live production credential would sit in
plaintext inside an ordinary application table with no secret protection.
Found by an automated security scan, not by the original implementation or
its review - this test is what would have caught it.

This test deliberately uses a synthetic, obviously-fake key rather than the
real ODDS_API_KEY from .env. A regression test whose own assertion failure
prints both operands of a failed `in` check (pytest's assertion rewriting
does this) would otherwise leak the real credential into console/CI output
at the exact moment the leak it's meant to catch reoccurs - defeating the
point of the test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import httpx
import pytest
from sqlalchemy import select

from src.ingest.theodds import poll_team_markets
from src.models.governance import IngestionRun

FAKE_KEY = "synthetic-test-key-not-a-real-secret"
FAKE_SETTINGS = SimpleNamespace(
    odds_api_key=FAKE_KEY,
    odds_api_base_url="https://api.the-odds-api.com/v4",
    odds_api_quota_floor=50,
)


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


async def test_failed_request_never_leaks_the_api_key_into_run_detail(db, redis):
    fake_request = httpx.Request(
        "GET",
        f"{FAKE_SETTINGS.odds_api_base_url}/sports/americanfootball_nfl/odds",
        params={"apiKey": FAKE_KEY, "regions": "us"},
    )
    fake_response = httpx.Response(401, request=fake_request, json={"message": "bad key"})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.ingest.theodds.get_settings", return_value=FAKE_SETTINGS),
        patch("src.ingest.theodds.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await poll_team_markets(db, redis)

    assert FAKE_KEY not in str(exc_info.value)

    run = await db.scalar(
        select(IngestionRun)
        .where(IngestionRun.source == "theodds")
        .order_by(IngestionRun.started_at.desc())
    )
    assert run is not None
    assert run.status == "failed"
    assert run.detail is not None
    assert FAKE_KEY not in run.detail
    assert run.detail == "RuntimeError: Odds API request failed: 401"
