"""Quota-guarded team-market polling from The Odds API.

CONSTRAINT #4: three defences, all from day one - season-aware polling,
generous intervals, and this quota guard reading x-requests-remaining. The
free tier allows 500 requests per month; below a configured floor of
remaining requests, the guard sets a Redis key with a 24h TTL that
suppresses all further polling until it expires.

CONSTRAINT #22: the quota helpers below take an explicit `redis` client
parameter rather than reaching for a module-level cached one. That is what
keeps them correct from both the FastAPI process (one persistent event
loop) and a Celery task (fresh event loop per invocation) - do not add a
global/cached Redis client here.

SCOPE NOTE (Task 6, Steps 1-4 only): `poll_team_markets`'s event-parsing
body and its `_match_game`/`_rows_for` helpers are deliberately not
implemented in this module yet. The Odds API's spread-sign convention has to
be checked against a captured live payload before it can be trusted - ESPN's
and nflverse's ingestion each hit a mirrored-sign bug from trusting
documentation over a real response, and that fixture capture costs one of
the 500 free monthly requests. That capture and the parsing it unlocks are
Task 6 Step 5, done separately. Only the quota guard - fully specifiable and
testable offline with fakeredis, no network call required - is implemented
here.
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

SOURCE = "theodds"
QUOTA_KEY = "odds_api:quota_exhausted"
QUOTA_TTL_SECONDS = 86400


async def is_quota_exhausted(redis: Redis) -> bool:
    return await redis.exists(QUOTA_KEY) == 1


async def set_quota_exhausted(redis: Redis) -> None:
    await redis.set(QUOTA_KEY, "1", ex=QUOTA_TTL_SECONDS)


async def clear_quota_exhausted(redis: Redis) -> None:
    await redis.delete(QUOTA_KEY)


async def poll_team_markets(db: AsyncSession, redis: Redis) -> int:
    """Poll h2h, spreads, and totals. Returns rows written.

    NOT YET IMPLEMENTED. Event parsing (`_match_game`, `_rows_for`) depends
    on a live fixture captured from The Odds API to verify the spread-sign
    convention before it's trusted - see the module docstring's SCOPE NOTE
    and task-6-brief.md Step 5.
    """
    raise NotImplementedError(
        "poll_team_markets is implemented in Task 6 Step 5, after a live "
        "fixture verifies The Odds API's spread-sign convention"
    )
