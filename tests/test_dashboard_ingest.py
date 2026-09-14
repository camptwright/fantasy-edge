"""homelab-dashboard article push: no-ops when unconfigured, reports success/
failure via its return value, never raises on delivery failure."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from src.utils.dashboard_ingest import post_article

UNCONFIGURED = SimpleNamespace(dashboard_ingest_url="", dashboard_ingest_token="")
CONFIGURED = SimpleNamespace(
    dashboard_ingest_url="https://admin.example.com/api/ingest/articles",
    dashboard_ingest_token="secret-token",
)


async def test_post_article_is_a_noop_and_returns_false_when_unconfigured():
    with patch("src.utils.dashboard_ingest.httpx.AsyncClient") as mock_client:
        with patch("src.utils.dashboard_ingest.get_settings", return_value=UNCONFIGURED):
            result = await post_article("Title", "Body")
    mock_client.assert_not_called()
    assert result is False


async def test_post_article_posts_the_expected_body_and_bearer_token():
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(
        return_value=httpx.Response(200, request=httpx.Request("POST", "https://x"))
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.dashboard_ingest.get_settings", return_value=CONFIGURED),
        patch("src.utils.dashboard_ingest.httpx.AsyncClient", return_value=mock_session),
    ):
        result = await post_article("Week 3 recap", "# Hi", tags=["fantasy-edge", "recap"])

    assert result is True
    mock_session.post.assert_awaited_once()
    args, kwargs = mock_session.post.call_args.args, mock_session.post.call_args.kwargs
    assert args[0] == "https://admin.example.com/api/ingest/articles"
    assert kwargs["json"] == {
        "title": "Week 3 recap",
        "body_markdown": "# Hi",
        "source": "fantasy-agent",
        "tags": ["fantasy-edge", "recap"],
    }
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    # Never auto-publishes to the public site - see this module's own
    # docstring for why.
    assert "publish" not in kwargs["json"]


async def test_post_article_swallows_delivery_failures_and_returns_false():
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.dashboard_ingest.get_settings", return_value=CONFIGURED),
        patch("src.utils.dashboard_ingest.httpx.AsyncClient", return_value=mock_session),
    ):
        result = await post_article("Title", "Body")

    assert result is False


async def test_post_article_reports_false_on_a_non_2xx_response():
    mock_session = AsyncMock()
    mock_session.post = AsyncMock(
        return_value=httpx.Response(403, request=httpx.Request("POST", "https://x"))
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.dashboard_ingest.get_settings", return_value=CONFIGURED),
        patch("src.utils.dashboard_ingest.httpx.AsyncClient", return_value=mock_session),
    ):
        result = await post_article("Title", "Body")

    assert result is False
