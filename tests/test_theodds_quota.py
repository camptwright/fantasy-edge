"""Quota guard for The Odds API.

CONSTRAINT #4: the free tier allows 500 requests per month. The guard reads
x-requests-remaining and, below the floor, sets a Redis key with a 24h TTL
that suppresses all further polling.

CONSTRAINT #22: quota helpers take an explicit redis client rather than
reaching for a module-level cached one, so the same functions are correct
from both the API process and a Celery task's fresh event loop.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from src.ingest.theodds import (
    QUOTA_KEY,
    clear_quota_exhausted,
    is_quota_exhausted,
    set_quota_exhausted,
)


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


async def test_guard_is_clear_by_default(redis):
    assert await is_quota_exhausted(redis) is False


async def test_setting_the_guard_blocks_polling(redis):
    await set_quota_exhausted(redis)
    assert await is_quota_exhausted(redis) is True


async def test_guard_expires_within_a_day(redis):
    await set_quota_exhausted(redis)
    ttl = await redis.ttl(QUOTA_KEY)
    assert 0 < ttl <= 86400


async def test_guard_can_be_cleared(redis):
    await set_quota_exhausted(redis)
    await clear_quota_exhausted(redis)
    assert await is_quota_exhausted(redis) is False
