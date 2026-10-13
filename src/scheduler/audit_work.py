"""Isolated worker loops for audit evidence; no serving promotion."""
import asyncio
from datetime import datetime,timezone
from src.db.client import get_worker_db
from src.scheduler.celery_app import celery_app


@celery_app.task(name='fantasy.observe_operations',soft_time_limit=20,time_limit=30)
def observe_operations():
    async def run():
        from src.services.operations_history import collect
        async with get_worker_db() as db:return await collect(db)
    return asyncio.run(run())


@celery_app.task(name='fantasy.refresh_fantasy_models',soft_time_limit=90,time_limit=120)
def refresh_fantasy_models():
    async def run():
        from sqlalchemy import select
        from src.models.sleeper import SleeperLeague
        from src.services.fantasy_read_model import refresh
        async with get_worker_db() as db:
            ids=list((await db.scalars(select(SleeperLeague.league_id).where(SleeperLeague.sport=='nfl'))).all())
        results=[]
        for league_id in ids:
            from sqlalchemy.exc import DBAPIError
            # A concurrent refresh/source transaction may invalidate a
            # repeatable-read snapshot. Retry with a fresh session, never with
            # the aborted transaction or a cross-loop engine.
            for attempt in range(3):
                try:
                    async with get_worker_db() as db:
                        result=await refresh(db,league_id)
                    results.append(result)
                    break
                except DBAPIError as exc:
                    if getattr(exc.orig,'sqlstate',None)!='40001' or attempt==2:raise
        return results
    return asyncio.run(run())


@celery_app.task(name='fantasy.research_shadow',soft_time_limit=240,time_limit=300)
def research_shadow():
    async def run():
        from src.services.research_shadow_ledger import capture,close
        async with get_worker_db() as db:
            return {'capture':await capture(db),'closes':await close(db)}
    return asyncio.run(run())


@celery_app.task(name='fantasy.retention_research',soft_time_limit=240,time_limit=300)
def retention_research():
    from src.services.retention_pipeline import execute
    return [{k:v for k,v in report.items() if k!='grades'} for report in asyncio.run(execute())]


@celery_app.task(name='fantasy.specialist_research',soft_time_limit=240,time_limit=300)
def specialist_research():
    from src.services.fantasy_specialist_prospective import execute
    return [{k:v for k,v in report.items() if k!='grades'} for report in asyncio.run(execute())]


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


@celery_app.task(name='fantasy.refresh_snap_counts',soft_time_limit=600,time_limit=720)
def refresh_snap_counts():
    async def run():
        from src.ingest.usage import refresh_snap_counts as refresh
        now=datetime.now(timezone.utc);season=now.year if now.month>=3 else now.year-1
        async with get_worker_db() as db:return await refresh(db,season)
    return asyncio.run(run())


@celery_app.task(name='fantasy.projection_engine_research',soft_time_limit=840,time_limit=900)
def projection_engine_research():
    """Freeze pregame engine projections, then grade them against Sleeper's."""
    async def run():
        from src.services.projection_engine_prospective import capture, report
        async with get_worker_db() as db:
            captured=await capture(db)
            graded=await report(db)
            depth=await report(db,'depth')
            from src.services.projection_engine_serving import refresh
            research=await refresh(db)
            from src.services import espn_projections, sleeper_trending
            espn=await espn_projections.capture(db)
            trending=await sleeper_trending.refresh(db)
            from src.services import schedule_strength
            sos=await schedule_strength.refresh(db)
            from src.services import outcome_prospective
            win=await outcome_prospective.capture(db)
            win_report=await outcome_prospective.report(db)
        return {'capture':captured,'espn':espn,'trending':trending,'schedule_strength':sos,'win_probability':{'captured':win,'statuses':win_report['statuses']},'statuses':graded['statuses'],
                'promotion_blockers':graded['promotion']['blockers'],
                'depth_statuses':depth['statuses'],'research':research,'serving_promoted':False}
    return asyncio.run(run())


@celery_app.task(name='fantasy.compress_raw_archive',soft_time_limit=1500,time_limit=1800)
def compress_raw_archive():
    """Lossless gzip of day-old append-only archive files; see raw_retention.COMPRESSIBLE."""
    from src.services.raw_retention import compress_daily
    return compress_daily()


@celery_app.task(name='fantasy.raw_retention_report',soft_time_limit=240,time_limit=300)
def raw_retention_report():
    async def run():
        from src.services.raw_retention import retain
        from src.scheduler.calibration import archive
        async with get_worker_db() as db:
            report=await retain(db)
        return {'manifest':archive('retention-manifests',report),'deleted':0,
            'candidate_bytes':report['candidate_bytes'],'status':report['status'],
            'compressed':report['compressed'],'bytes_saved':report['bytes_saved']}
    return asyncio.run(run())
