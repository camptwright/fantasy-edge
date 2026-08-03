"""The Odds API - game odds only (h2h/spreads/totals).

CONSTRAINT #4: free tier is 500 requests/month, all defences live here:
  (a) season-aware polling      - caller's job (see game_sync/odds_monitor
                                   scheduling in celery_app), this module just
                                   exposes is_in_season() reuse via settings.
  (b) 300s in-season / 21600s off-season interval - also scheduler's job.
  (c) quota guard                - THIS module's job. Every response header
                                    x-requests-remaining is logged, and once
                                    it drops below the floor we latch a Redis
                                    flag so the scheduler skips polls without
                                    even importing this module's call path.

CONSTRAINT #5: player-prop endpoints (`/events/{id}/odds` with markets like
`player_points`) are NOT on the free tier. This module only ever requests
h2h/spreads/totals from the /sports/{sport}/odds endpoint. Do not add a props
method here - see props_agent.py / Underdog instead.

Every function here takes an explicit `redis` client rather than reaching
for a global one - see redis_client.py's module docstring for why a cached
client can't safely be shared across Celery's per-task event loops.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from config.settings import get_settings, get_sport_config
from src.data.cache.redis_client import is_quota_exhausted, set_quota_exhausted
from src.data.providers.base import ProviderError, fetch_json
from src.utils.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

# Only these three. Anything else is a paid-tier market (constraint #5).
ALLOWED_MARKETS = {"h2h", "spreads", "totals"}


class QuotaExhaustedError(ProviderError):
    """Raised when the quota guard blocks a call before it goes out."""


async def _guarded_get(
    redis: Redis, path: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    if await is_quota_exhausted(redis):
        log.warning("theodds.quota_guard_blocked", path=path)
        raise QuotaExhaustedError("Odds API quota flag is set; skipping call")

    settings = get_settings()
    if not settings.odds_api_key:
        raise ProviderError("ODDS_API_KEY is not configured")

    data, response = await fetch_json(
        f"{BASE_URL}{path}",
        params={**params, "apiKey": settings.odds_api_key},
        return_response=True,
    )

    remaining_header = response.headers.get("x-requests-remaining")
    used_header = response.headers.get("x-requests-used")
    if remaining_header is not None:
        remaining = int(remaining_header)
        log.info("theodds.quota", remaining=remaining, used=used_header, path=path)
        if remaining < settings.odds_api_quota_floor:
            log.warning("theodds.quota_floor_hit", remaining=remaining)
            await set_quota_exhausted(redis, remaining)
    else:
        # The API always sends this header on success; its absence is itself
        # a signal something is wrong (e.g. an error page slipped past the
        # status-code check), so it's logged rather than assumed fine.
        log.warning("theodds.missing_quota_header", path=path)

    return data


async def get_odds(
    redis: Redis, sport: str, *, regions: str = "us"
) -> list[dict[str, Any]]:
    """Game odds for one sport across books.

    Returns The Odds API's native event shape: each element has
    `id`, `commence_time`, `home_team`, `away_team`, `bookmakers[].markets[]`.
    """
    cfg = get_sport_config(sport)
    odds_api_key_slug = cfg.get("odds_api_key")
    if not odds_api_key_slug:
        raise ProviderError(f"{sport} has no odds_api_key configured in sports.yaml")

    markets = [m for m in cfg.get("markets", []) if m in ALLOWED_MARKETS]
    if not markets:
        raise ProviderError(f"{sport} has no allowed markets configured")

    return await _guarded_get(
        redis,
        f"/sports/{odds_api_key_slug}/odds",
        {
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "american",
            "dateFormat": "iso",
        },
    )


async def get_scores(
    redis: Redis, sport: str, *, days_from: int = 1
) -> list[dict[str, Any]]:
    """Completed/live scores. Used sparingly - this is a separate quota line item."""
    cfg = get_sport_config(sport)
    odds_api_key_slug = cfg["odds_api_key"]
    return await _guarded_get(
        redis,
        f"/sports/{odds_api_key_slug}/scores",
        {"daysFrom": days_from, "dateFormat": "iso"},
    )
