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

CONSTRAINT #1 GENERALISES TO REDIS, NOT JUST THE DB ENGINE. A
`redis.asyncio.Redis` client's connections are bound to the asyncio event
loop that was running when it first connected. `get_redis()`'s module-level
cache is only safe for a process with ONE persistent event loop for its
whole lifetime - the FastAPI/uvicorn process. Every Celery task runs its own
`asyncio.run()`, which creates a fresh loop and destroys it on completion;
reusing `get_redis()`'s cached client across two different `asyncio.run()`
calls hands the second call a client still holding sockets bound to the
FIRST (now-closed) loop, and it fails with
`RuntimeError: Task ... got Future ... attached to a different loop`
followed by `RuntimeError: Event loop is closed` while trying to clean up.
This was caught empirically on CT 100: `odds_tick` worked on its first
scheduled run and threw exactly that traceback on its second. `get_worker_
redis()` is the fix - same NullPool-per-task shape as `get_worker_db()`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
    """Client for the API/FastAPI process ONLY - it owns one persistent
    event loop for its entire lifetime, so caching a client here is safe.
    NEVER call this from a Celery task; use `get_worker_redis()` instead.
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


@asynccontextmanager
async def get_worker_redis() -> AsyncIterator[Redis]:
    """Fresh client per Celery task, disposed before the task's `asyncio.
    run()` closes its loop. Mirrors `get_worker_db()`'s NullPool-per-task
    shape for exactly the same reason: nothing here may outlive one task's
    event loop.

        @celery_app.task
        def some_tick():
            async def _run():
                async with get_worker_redis() as redis:
                    ...
            asyncio.run(_run())
    """
    settings = get_settings()
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


# ----------------------------------------------------------- quota guard ----
# These take an explicit `redis` client rather than reaching for a global,
# so the same functions work correctly from both the API's shared client
# and a worker task's per-task client.


async def is_quota_exhausted(redis: Redis) -> bool:
    """CONSTRAINT #4c. Checked before every Odds API call."""
    return bool(await redis.exists(KEY_QUOTA_EXHAUSTED))


async def set_quota_exhausted(redis: Redis, remaining: int, ttl_seconds: int = 86400) -> None:
    """Latch the quota flag for 24h.

    The TTL is the recovery mechanism: the free tier resets monthly, but a
    24h latch means one bad reading cannot permanently disable polling, and
    a genuinely exhausted quota re-latches on the next attempt.
    """
    await redis.set(KEY_QUOTA_EXHAUSTED, str(remaining), ex=ttl_seconds)


async def clear_quota_exhausted(redis: Redis) -> None:
    await redis.delete(KEY_QUOTA_EXHAUSTED)
