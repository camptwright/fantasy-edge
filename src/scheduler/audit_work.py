"""Isolated worker loops for audit evidence; no serving promotion."""
import asyncio
from datetime import datetime,timezone
from src.db.client import get_worker_db
from src.scheduler.celery_app import celery_app


@celery_app.task(name='fantasy.research_shadow',soft_time_limit=240,time_limit=300)
def research_shadow():
    async def run():
        from src.services.research_shadow_ledger import capture,close
        async with get_worker_db() as db:
            return {'capture':await capture(db),'closes':await close(db)}
    return asyncio.run(run())


@celery_app.task(name='fantasy.register_nfl_lab',soft_time_limit=240,time_limit=300)
def register_nfl_lab():
    async def run():
        from src.services.nfl_lab_registry import execute
        async with get_worker_db() as db:return await execute(db)
    return asyncio.run(run())


@celery_app.task(name='fantasy.refresh_nfl_stats',soft_time_limit=1500,time_limit=1800)
def refresh_nfl_stats():
    async def run():
        from src.services.nfl_epa_feed import refresh
        now=datetime.now(timezone.utc);season=now.year if now.month>=3 else now.year-1
        async with get_worker_db() as db:return await refresh(db,season)
    return asyncio.run(run())


@celery_app.task(name='fantasy.raw_retention_report',soft_time_limit=240,time_limit=300)
def raw_retention_report():
    async def run():
        from src.services.raw_retention import plan
        from src.scheduler.calibration import archive
        async with get_worker_db() as db:
            report=await plan(db)
        return {'manifest':archive('retention-manifests',report),'deleted':0,
            'candidate_bytes':report['candidate_bytes'],'status':'dry_run'}
    return asyncio.run(run())
