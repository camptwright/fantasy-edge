"""Pushes the latest recommendations narrative to homelab-dashboard's
Fantasy tile, via the same /api/ingest/articles path OpenClaw/Adjutant
already post through (bearer-token auth, bypasses Cloudflare Access -
see that repo's src/middleware.ts).

Mirrors src/utils/alerts.py's notify(): this must never crash the Celery
task that calls it. A dashboard push failing (misconfigured token,
dashboard down) is not a reason to fail the underlying narrative
generation/read - every failure path is swallowed after logging, same as
alerts.py's own reasoning for ntfy.

Deliberately never sends `publish: true` - a pushed narrative lands as a
draft in the dashboard's private admin view only, never the public
public_articles view. homelab-dashboard's own ingest route treats that as
a separate, explicit, human-reviewed action; this module has no opinion
on when (or whether) that ever happens.
"""

from __future__ import annotations

import logging

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


async def post_article(title: str, body_markdown: str, *, tags: list[str] | None = None) -> bool:
    """Returns True on a confirmed 2xx post, False on any failure (including
    "not configured") - callers that want to know whether the push actually
    landed (e.g. to decide whether to log a Celery task result) get a real
    signal instead of having to inspect logs."""
    settings = get_settings()
    if not settings.dashboard_ingest_url or not settings.dashboard_ingest_token:
        logger.warning("dashboard ingest not configured, dropping article: %s", title)
        return False

    body = {
        "title": title,
        "body_markdown": body_markdown,
        "source": "fantasy-agent",
    }
    if tags:
        body["tags"] = tags

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                settings.dashboard_ingest_url.rstrip("/"),
                json=body,
                headers={"Authorization": f"Bearer {settings.dashboard_ingest_token}"},
            )
            response.raise_for_status()
        return True
    except httpx.HTTPError:
        logger.exception("dashboard article push failed: %s", title)
        return False
