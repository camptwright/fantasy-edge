"""Fork-safe Celery wrappers for the NFL ingestion primitives."""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

from config.settings import get_settings
from src.db.client import get_worker_db
from src.ingest.bovada import poll_team_markets as poll_bovada_markets
from src.ingest.espn import sync_scoreboard
from src.ingest.mlb import sync_schedule as sync_mlb_schedule
from src.ingest.nhl import sync_schedule as sync_nhl_schedule
from src.ingest.pinnacle import poll_team_markets as poll_pinnacle_markets
from src.ingest.theodds import poll_team_markets
from src.ingest.underdog import ingest_props
from src.ingest.sleeper import sync_sleeper_account
from src.ingest.espn_fantasy import sync_espn_fantasy_account
from src.models.governance import RecommendationSnapshot
from src.scheduler.celery_app import celery_app
from src.services.reconciliation import run_health_checks
from src.services.recommendations import generate_narrative, get_valid_narrative
from src.utils.alerts import notify
from src.utils.dashboard_ingest import post_article


@celery_app.task(name='fantasy.sync_fantasy_market', soft_time_limit=180, time_limit=210)
def sync_fantasy_market():
    from src.services.fantasy_market import collect
    async def run():
        from src.services.settlement_evidence import collect as collect_rules
        rules=await collect_rules()
        async with get_worker_db() as db:
            return {'market':await collect(db),'settlement':rules}
    return asyncio.run(run())


@celery_app.task(name='fantasy.archive_event_weather', soft_time_limit=500, time_limit=540)
def archive_event_weather():
    async def run():
        from src.services.event_weather import collect
        async with get_worker_db() as db:
            return await collect(db)
    report=asyncio.run(run())
    return {'games':len(report['rows']),'truncated':report['truncated']}


@celery_app.task(name='fantasy.capture_ledger_closes', soft_time_limit=110, time_limit=120)
def capture_ledger_closes():
    async def run():
        from sqlalchemy import text
        from src.services.betting_ledger import capture_closes
        async with get_worker_db() as db:
            await db.execute(text('SELECT pg_advisory_xact_lock(78241903)'))
            return await capture_closes(db)
    return asyncio.run(run())


@celery_app.task(name="fantasy.sync_espn")
def sync_espn() -> dict:
    async def run() -> dict:
        written = {}
        failures = {}
        for sport in get_settings().espn_sports:
            try:
                # Isolate both transactions and connection failures by sport.
                async with get_worker_db() as db:
                    written[sport] = await sync_scoreboard(db, sport=sport)
            except Exception as exc:
                # HTTP/ingestion failures are recorded by record_run; never
                # duplicate that audit row or suppress the other sport jobs.
                failures[sport]=type(exc).__name__
                logging.getLogger(__name__).exception('ESPN scoreboard failed for %s',sport)
        return {'rows_written':written,'failures':failures}

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
def sync_sleeper() -> dict[str, dict[str, int | str]]:
    async def run() -> dict[str, dict[str, int | str]]:
        async with get_worker_db() as db:
            return await sync_sleeper_account(db)

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"Sleeper sync failed: {exc}", title="Fantasy Edge: Sleeper"))
        raise


@celery_app.task(name="fantasy.sync_espn_fantasy")
def sync_espn_fantasy() -> dict[str, dict[str, int | str]]:
    # Quiet no-op until ESPN_LEAGUE_IDS/ESPN_S2/ESPN_SWID are configured -
    # same pattern as theodds.poll_team_markets' odds_api_key check, since
    # this is an optional integration most deployments of this app will
    # never turn on, and a raised ValueError on every 15-minute beat tick
    # would otherwise fire a real ntfy alert for a deliberately-unset
    # feature rather than a genuine failure.
    settings = get_settings()
    if not settings.espn_league_ids or not settings.espn_s2 or not settings.espn_swid:
        return {}

    async def run() -> dict[str, dict[str, int | str]]:
        async with get_worker_db() as db:
            return await sync_espn_fantasy_account(db)

    try:
        return asyncio.run(run())
    except Exception as exc:
        asyncio.run(notify(f"ESPN Fantasy sync failed: {exc}", title="Fantasy Edge: ESPN Fantasy"))
        raise


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
    # Keep an inert handler for messages queued before the schedule removal.
    return {"written": 0, "parked": 0, "disabled_by_policy": 1}


@celery_app.task(name="fantasy.check_data_health")
def check_data_health() -> dict[str, int]:
    async def run() -> list[str]:
        async with get_worker_db() as db:
            issues = await run_health_checks(db)
            return [f"{issue.check}: {issue.detail}" for issue in issues]

    messages = asyncio.run(run())
    if messages:
        delivered = asyncio.run(
            notify(
                "\n".join(messages),
                title=f"Fantasy Edge: {len(messages)} data-health issue(s)",
            )
        )
        if not delivered:
            raise RuntimeError(f'Data-health alert delivery failed ({len(messages)} issues); inspect notification logs')
    return {"issues": len(messages)}


@celery_app.task(name="fantasy.generate_recommendations")
def generate_recommendations() -> dict[str, int]:
    """Persist deterministic quote summaries; GET only reads validated snapshots."""

    async def run() -> int:
        async with get_worker_db() as db:
            result = await generate_narrative(db, with_evidence=True)
            narrative = result['narrative']
            db.add(RecommendationSnapshot(narrative=narrative, quote_ids=result['quote_ids']))
            await db.commit()
            return len(narrative)

    try:
        return {"narrative_length": asyncio.run(run())}
    except Exception as exc:
        asyncio.run(
            notify(f"Recommendation generation failed: {exc}", title="Fantasy Edge: Recommendations")
        )
        raise


@celery_app.task(name="fantasy.post_narrative_to_dashboard")
def post_narrative_to_dashboard() -> dict[str, bool]:
    """Pushes the latest *valid* narrative (src/services/recommendations.py's
    get_valid_narrative - same freshness/quote-evidence gate GET
    /recommendations applies) to homelab-dashboard as a source=fantasy-agent
    article, via src/utils/dashboard_ingest.py.

    Deliberately on a much slower cadence than generate_recommendations'
    30-minute cycle (see beat_schedule in celery_app.py) - the dashboard's
    Fantasy tile only ever shows the single newest fantasy-agent article,
    so posting one every 30 minutes would just spam its /content archive
    with near-duplicate rows for no one to read; a daily digest is enough
    for a "check in once a day" summary.

    A None narrative (nothing generated yet, or the latest one expired/its
    evidence moved on) is not an error - it just means there's nothing
    worth posting this cycle, so this returns cleanly without calling
    post_article at all."""

    async def run() -> bool:
        async with get_worker_db() as db:
            result = await get_valid_narrative(db)
            narrative = result["narrative"]
            if narrative is None:
                return False
            generated_at = result["generated_at"]
            title = f"Fantasy Edge recap — {generated_at[:10]}"
            return await post_article(title, narrative, tags=["fantasy-edge", "recap"])

    return {"posted": asyncio.run(run())}
