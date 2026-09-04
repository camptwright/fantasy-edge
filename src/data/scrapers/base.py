"""Shared scraping primitives: TLS-impersonated fetch, pacing, raw archive.

Every direct-to-source scraper (DraftKings, Pinnacle, Bovada, PrizePicks -
see Phase 1 of the scraping plan) subclasses `BaseScraper` rather than
calling `httpx`/`curl_cffi` directly, so pacing and raw-payload archival are
never something a new source can accidentally skip.

Pacing is per-instance, not cross-process: a Celery task creates one scraper
instance per run and Celery beat already spaces different runs of the same
task by minutes (see `celery_app.py`'s `beat_schedule`), so an in-process
`min_interval` is enough to pace the handful of requests one run makes
(e.g. DK's eventgroup -> category -> subcategory chain) without needing a
Redis-backed token bucket. Add one later only if a specific source (e.g. a
future Sports Reference scraper's documented 20 req/min ban threshold)
actually needs pacing that survives across separate task invocations.

Every response is archived before `raise_for_status()` runs, so a failing
request's body (often the most useful thing for diagnosing a schema/anti-bot
change) is captured too, not just successful ones.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from config.settings import get_settings


class ScraperError(RuntimeError):
    """Raised on a non-2xx response or transport failure, after archiving."""


class BaseScraper:
    source: str = "base"
    # Pinned rather than "latest chrome" - impersonation targets drift with
    # real Chrome releases, so an unpinned target silently degrades as
    # curl_cffi's bundled fingerprints age. Bump deliberately, not implicitly.
    impersonate: str = "chrome124"
    min_interval: float = 2.0

    def __init__(self) -> None:
        self._last_request: float = 0.0

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    async def fetch_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a URL, archive the raw response, return parsed JSON.

        Raises ScraperError on a transport failure or non-2xx status - the
        raw body is archived either way before the exception is raised, so
        the archive is what you replay to diagnose the failure.
        """
        await self._throttle()
        async with AsyncSession() as session:
            try:
                response = await session.get(
                    url,
                    headers=headers,
                    params=params,
                    impersonate=self.impersonate,
                    timeout=30,
                )
            except RequestException as exc:
                raise ScraperError(f"{self.source}: request to {url} failed: {exc}") from exc

        await self._archive(url, response.content)

        if response.status_code >= 400:
            raise ScraperError(
                f"{self.source}: {url} returned HTTP {response.status_code}"
            )
        return response.json()

    async def _archive(self, url: str, content: bytes) -> None:
        await asyncio.to_thread(self._archive_sync, url, content)

    def _archive_sync(self, url: str, content: bytes) -> None:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        root = Path(get_settings().raw_archive_dir)
        target_dir = root / self.source / now.strftime("%Y-%m-%d")
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{ts}_{url_hash}.json.gz").write_bytes(gzip.compress(content))
