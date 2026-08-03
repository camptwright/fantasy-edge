"""Celery task bodies. CONSTRAINT #1: every task opens its own
`get_worker_db()` NullPool session created INSIDE the task and runs via
`asyncio.run()` - never a module-level engine, never a reused event loop.

The same rule applies to Redis, not just Postgres - `get_worker_redis()`,
never the API-only `get_redis()`. See redis_client.py's module docstring:
a cached asyncio Redis client is bound to whichever event loop first used
it, and every task here gets a brand new loop from `asyncio.run()`.
"""

from __future__ import annotations

import asyncio
import time

from config.settings import all_sports, get_settings, get_sport_config, is_in_season
from src.agents.alert_agent import AlertAgent
from src.agents.clv_tracker import ClvTracker
from src.agents.game_sync_agent import GameSyncAgent
from src.agents.odds_monitor import OddsMonitor
from src.agents.props_agent import PropsAgent
from src.agents.value_agent import ValueAgent
from src.data.cache.db_client import get_worker_db
from src.data.cache.redis_client import get_worker_redis
from src.models.orm import Game
from src.scheduler.celery_app import celery_app
from src.utils.logging import get_logger

log = get_logger(__name__)

ODDS_LAST_POLL_KEY = "scheduler:odds_last_poll:{sport}"


@celery_app.task(name="src.scheduler.tasks.game_sync_tick")
def game_sync_tick() -> None:
    async def _run() -> None:
        async with get_worker_db() as db:
            await GameSyncAgent().sync_all(db, all_sports())

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.props_tick")
def props_tick() -> None:
    """Underdog's own catalog only lists sports currently offering picks,
    so it's effectively self-gating for season awareness - no per-sport
    interval logic needed here, unlike odds_tick."""

    async def _run() -> None:
        async with get_worker_db() as db:
            await PropsAgent().ingest(db)

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.odds_tick")
def odds_tick() -> None:
    """CONSTRAINT #4: season-aware polling with per-sport interval,
    enforced here rather than in the beat schedule (see celery_app.py)."""

    async def _run() -> None:
        settings = get_settings()
        now = time.time()

        # One client for the whole tick, not one per sport - a single
        # get_worker_redis() context lives inside this one asyncio.run()
        # loop the entire time, which is exactly what makes it safe. Note
        # OddsMonitor.poll_sport() below opens its OWN get_worker_redis()
        # internally too (it needs pub/sub + last-seen-price keys); that's
        # fine, it's still inside the same outer loop, just a second
        # short-lived connection alongside this one.
        async with get_worker_redis() as redis:
            for sport in all_sports():
                cfg = get_sport_config(sport)
                if not cfg.get("odds_api_key"):
                    continue

                in_season = is_in_season(sport, time.gmtime(now).tm_mon)
                interval = (
                    settings.poll_interval_in_season
                    if in_season
                    else settings.poll_interval_off_season
                )

                key = ODDS_LAST_POLL_KEY.format(sport=sport)
                last_raw = await redis.get(key)
                if last_raw is not None and now - float(last_raw) < interval:
                    continue

                async with get_worker_db() as db:
                    try:
                        await OddsMonitor().poll_sport(db, sport)
                    except Exception:
                        log.exception("odds_tick.poll_failed", sport=sport)
                await redis.set(key, str(now))

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.run_value_agent_for_game")
def run_value_agent_for_game(game_id: str) -> None:
    """Triggered by OddsMonitor when it detects significant line movement
    on a game (see odds_monitor.py's lazy import of this task)."""

    async def _run() -> None:
        async with get_worker_db() as db:
            game = await db.get(Game, game_id)
            if game is not None:
                await ValueAgent().evaluate_game(db, game)

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.value_agent_tick")
def value_agent_tick() -> None:
    """Catch-all sweep: evaluates every sport's upcoming games, not just
    ones OddsMonitor flagged as moved - a game whose line never moves but
    was simply mispriced from the start would otherwise never get a signal.
    """

    async def _run() -> None:
        async with get_worker_db() as db:
            agent = ValueAgent()
            for sport in all_sports():
                try:
                    await agent.evaluate_upcoming(db, sport)
                except Exception:
                    log.exception("value_agent_tick.sport_failed", sport=sport)

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.clv_tracker_tick")
def clv_tracker_tick() -> None:
    async def _run() -> None:
        async with get_worker_db() as db:
            tracker = ClvTracker()
            for sport in all_sports():
                await tracker.backfill_pending(db, sport)

    asyncio.run(_run())


@celery_app.task(name="src.scheduler.tasks.send_alert_for_signal")
def send_alert_for_signal(signal_id: str) -> None:
    """Triggered by ValueAgent immediately after persisting a signal (see
    value_agent.py's lazy import of this task)."""

    async def _run() -> None:
        async with get_worker_db() as db:
            await AlertAgent().send_by_id(db, signal_id)

    asyncio.run(_run())
