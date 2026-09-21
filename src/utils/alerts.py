"""Canary/anomaly alerting via the homelab's self-hosted ntfy instance.

Not `ntfy.sh` - reekserver-1 runs its own ntfy (see the ntfy project's
DEPLOYMENT.md), reachable over the same shared Cloudflare Tunnel this app's
dashboard already uses, so this is a plain HTTPS POST rather than anything
requiring Docker network wiring.

Alerting must never crash an ingestion run: a scraper finding its own
anomaly (empty slate, schema drift) is exactly the moment ntfy itself might
also be unreachable, and a raised exception here would mask the original
finding behind an unrelated failure. Every failure path is swallowed after
logging.
"""

from __future__ import annotations

import logging

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


def bounded_message(message: str, limit: int = 3500) -> bytes:
    raw=message.encode('utf-8')
    if len(raw)<=limit:return raw
    suffix=b'\n[Truncated; inspect data-health logs for remaining issues.]'
    return raw[:limit-len(suffix)].decode('utf-8',errors='ignore').encode('utf-8')+suffix


async def notify(message: str, *, title: str | None = None) -> bool:
    settings = get_settings()
    if not settings.ntfy_base_url or not settings.ntfy_topic:
        logger.warning("ntfy not configured, dropping alert: %s", message)
        return False

    headers = {}
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {settings.ntfy_token}"
    if title:
        headers["Title"] = title

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.ntfy_base_url.rstrip('/')}/{settings.ntfy_topic}",
                content=bounded_message(message),
                headers=headers,
            )
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception("ntfy alert failed to send")
        return False
