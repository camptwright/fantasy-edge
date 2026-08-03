"""Redis access.

Redis holds three kinds of state here, and it is worth being explicit about
which is which because CONSTRAINT #6 exists precisely because these got
confused once:

  1. Ephemeral operational flags  - quota exhaustion, alert cooldowns. TTL'd.
  2. Last-known values            - previous odds, for movement detection.
  3. Pub/sub channels             - line-movement fanout.

What Redis must NEVER hold is deduplication state for props. That lived here
once as marker keys with no TTL; the key space grew without bound, every
insert did a full membership check against it, and the pipeline froze. Prop
dedup belongs in Postgres where the uniqueness is actually enforced.
"""

from __future__ import annotations

from redis.asyncio import Redis

from config.settings import get_settings

# Channel used by odds_monitor -> value_agent fanout.
CHANNEL_LINE_MOVEMENT = "fantasy_edge:line_movement"

# Operational flag keys.
KEY_QUOTA_EXHAUSTED = "odds_api:quota_exhausted"
KEY_ODDS_LAST_SEEN = "odds:last:{sport}:{game_id}:{market}:{bookmaker}:{outcome}"
KEY_ALERT_COOLDOWN = "alert:cooldown:{signal_key}"

_client: Redis | None = None


def get_redis() -> Redis:
    """Process-wide client.

    redis-py's asyncio client is safe to share within one process and lazily
    reconnects, so unlike the SQLAlchemy engine this does not need the
    fork-safety dance - Celery tasks create their connections on first use
    after the fork.
    """
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ----------------------------------------------------------- quota guard ----


async def is_quota_exhausted() -> bool:
    """CONSTRAINT #4c. Checked before every Odds API call."""
    return bool(await get_redis().exists(KEY_QUOTA_EXHAUSTED))


async def set_quota_exhausted(remaining: int, ttl_seconds: int = 86400) -> None:
    """Latch the quota flag for 24h.

    The TTL is the recovery mechanism: the free tier resets monthly, but a
    24h latch means one bad reading cannot permanently disable polling, and
    a genuinely exhausted quota re-latches on the next attempt.
    """
    await get_redis().set(KEY_QUOTA_EXHAUSTED, str(remaining), ex=ttl_seconds)


async def clear_quota_exhausted() -> None:
    await get_redis().delete(KEY_QUOTA_EXHAUSTED)
