"""Shared HTTP plumbing for providers.

One place for timeouts, retries and the user-agent so a provider module is
only about parsing its own payload shape.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from src.utils.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
# Underdog and ESPN both 403 a bare python-httpx UA.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class ProviderError(RuntimeError):
    """Raised when a provider is unreachable or returns an unusable payload."""


async def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 2,
    backoff: float = 1.5,
    return_response: bool = False,
) -> Any:
    """GET a JSON document with bounded retries.

    Only 5xx and transport errors are retried. A 4xx is a permanent problem
    (bad key, bad sport slug, quota) and retrying it on a metered API would
    spend the budget three times for one mistake.

    `return_response` yields (data, response) so callers can read rate-limit
    headers - the Odds API quota guard needs x-requests-remaining.
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(url, params=params, headers=merged_headers)

            if response.status_code >= 500:
                last_error = ProviderError(f"{url} returned {response.status_code}")
                if attempt < retries:
                    await asyncio.sleep(backoff * (2**attempt))
                    continue
                raise last_error

            if response.status_code >= 400:
                # Surface the body: the Odds API explains quota problems there.
                raise ProviderError(
                    f"{url} returned {response.status_code}: {response.text[:300]}"
                )

            data = response.json()
            return (data, response) if return_response else data

        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(backoff * (2**attempt))
                continue
            raise ProviderError(f"{url} unreachable: {exc}") from exc

    raise ProviderError(f"{url} failed: {last_error}")
