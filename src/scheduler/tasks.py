"""Fork-safe Celery wrappers for the NFL ingestion primitives."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from config.settings import get_settings
from src.db.client import get_worker_db
from src.ingest.bovada import poll_team_markets as poll_bovada_markets
from src.ingest.espn import sync_scoreboard
from src.ingest.mlb import sync_schedule as sync_mlb_schedule
from src.ingest.nhl import sync_schedule as sync_nhl_schedule
from src.ingest.pinnacle import poll_team_markets as poll_pinnacle_markets
from src.ingest.prizepicks import ingest_props as ingest_prizepicks_props
from src.ingest.theodds import poll_team_markets
from src.ingest.underdog import ingest_props
from src.ingest.sleeper import sync_sleeper_account
from src.scheduler.celery_app import celery_app
from src.services.reconciliation import run_health_checks
from src.utils.alerts import notify


@celery_app.task(name="fantasy.sync_espn")
def sync_espn() -> dict[str, int]:
    async def run() -> dict[str, int]:
        written = {}
        async with get_worker_db() as db:
            # espn_sports, not supported_sports: MLB's and NHL's schedule/
            # scores come from their own official APIs instead
            # (fantasy.sync_mlb, fantasy.sync_nhl) - see config/settings.py's
            # espn_sports docstring.
            for sport in get_settings().espn_sports:
                written[sport] = await sync_scoreboard(db, sport=sport)
        return written

    return asyncio.run(run())


@celery_app.task(name="fantasy.sync_mlb")
def sync_mlb() -> int:
    async def run() -> int:
        async with get_worker_db() as db:
            return await sync_mlb_schedule(db)

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"MLB schedule sync failed: {exc}", title="Fantasy Edge: MLB"))
        raise


@celery_app.task(name="fantasy.sync_nhl")
def sync_nhl() -> int:
    async def run() -> int:
        async with get_worker_db() as db:
            return await sync_nhl_schedule(db)

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"NHL schedule sync failed: {exc}", title="Fantasy Edge: NHL"))
        raise


@celery_app.task(name="fantasy.sync_underdog")
def sync_underdog() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with get_worker_db() as db:
            written, parked = await ingest_props(db)
            return {"written": written, "parked": parked}

    return asyncio.run(run())


@celery_app.task(name="fantasy.sync_team_markets")
def sync_team_markets() -> dict[str, int]:
    async def run() -> dict[str, int]:
        # Never use a module-cached Redis client in a task: every asyncio.run
        # call has a distinct event loop (constraint #22).
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        written = {}
        try:
            async with get_worker_db() as db:
                # One quota guard covers every sport (see poll_team_markets'
                # own docstring) - polling nfl then ncaaf in the same task
                # run means a mid-loop quota trip correctly stops the rest.
                for sport in get_settings().supported_sports:
                    written[sport] = await poll_team_markets(db, redis, sport=sport)
        finally:
            await redis.aclose()
        return written

    return asyncio.run(run())


@celery_app.task(name="fantasy.sync_sleeper")
def sync_sleeper() -> dict[str, dict[str, int]]:
    async def run() -> dict[str, dict[str, int]]:
        async with get_worker_db() as db:
            return await sync_sleeper_account(db)

    return asyncio.run(run())


@celery_app.task(name="fantasy.sync_pinnacle")
def sync_pinnacle() -> dict[str, int]:
    async def run() -> dict[str, int]:
        written = {}
        async with get_worker_db() as db:
            for sport in get_settings().supported_sports:
                written[sport] = await poll_pinnacle_markets(db, sport=sport)
        return written

    try:
        return asyncio.run(run())
    except Exception as exc:
        # record_run already persisted this failure to ingestion_runs (see
        # its own docstring for why alerting doesn't live there); this is
        # the one alert this specific run actually needed sent.
        asyncio.run(notify(f"Pinnacle sync failed: {exc}", title="Fantasy Edge: Pinnacle"))
        raise


@celery_app.task(name="fantasy.sync_bovada")
def sync_bovada() -> dict[str, int]:
    async def run() -> dict[str, int]:
        written = {}
        async with get_worker_db() as db:
            for sport in get_settings().supported_sports:
                written[sport] = await poll_bovada_markets(db, sport=sport)
        return written

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"Bovada sync failed: {exc}", title="Fantasy Edge: Bovada"))
        raise


@celery_app.task(name="fantasy.sync_prizepicks")
def sync_prizepicks() -> dict[str, int]:
    async def run() -> dict[str, int]:
        async with get_worker_db() as db:
            written, parked = await ingest_prizepicks_props(db)
            return {"written": written, "parked": parked}

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"PrizePicks sync failed: {exc}", title="Fantasy Edge: PrizePicks"))
        raise


@celery_app.task(name="fantasy.check_data_health")
def check_data_health() -> dict[str, int]:
    async def run() -> list[str]:
        async with get_worker_db() as db:
            issues = await run_health_checks(db)
            return [f"{issue.check}: {issue.detail}" for issue in issues]

    messages = asyncio.run(run())
    if messages:
        asyncio.run(
            notify(
                "\n".join(messages),
                title=f"Fantasy Edge: {len(messages)} data-health issue(s)",
            )
        )
    return {"issues": len(messages)}
