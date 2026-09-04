"""ntfy alerting: no-ops when unconfigured, never raises on delivery failure."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from src.utils.alerts import notify

UNCONFIGURED = SimpleNamespace(ntfy_base_url="", ntfy_topic="", ntfy_token="")
CONFIGURED = SimpleNamespace(
    ntfy_base_url="https://ntfy.example.com",
    ntfy_topic="fantasy-edge-alerts",
    ntfy_token="secret-token",
)


async def test_notify_is_a_noop_when_ntfy_is_not_configured():
    with patch("src.utils.alerts.httpx.AsyncClient") as mock_client:
        with patch("src.utils.alerts.get_settings", return_value=UNCONFIGURED):
            await notify("DK scraper returned 0 rows")
    mock_client.assert_not_called()


async def test_notify_posts_to_the_configured_topic_with_auth():
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(
        return_value=httpx.Response(200, request=httpx.Request("POST", "https://x"))
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.alerts.get_settings", return_value=CONFIGURED),
        patch("src.utils.alerts.httpx.AsyncClient", return_value=mock_session),
    ):
        await notify("DK scraper returned 0 rows", title="Scraper anomaly")

    mock_session.post.assert_awaited_once()
    url, kwargs = mock_session.post.call_args.args, mock_session.post.call_args.kwargs
    assert url[0] == "https://ntfy.example.com/fantasy-edge-alerts"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert kwargs["headers"]["Title"] == "Scraper anomaly"


async def test_notify_swallows_delivery_failures():
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.alerts.get_settings", return_value=CONFIGURED),
        patch("src.utils.alerts.httpx.AsyncClient", return_value=mock_session),
    ):
        await notify("this must not raise even though ntfy is unreachable")
