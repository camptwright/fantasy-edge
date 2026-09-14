"""Daily candidate evaluation and timestamped news archive.

Reports remain experimental. Serving probabilities never load these files.
"""
import asyncio
import json
import os
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from redis.asyncio import Redis
from config.settings import get_settings
from src.scheduler.celery_app import celery_app
from src.data.news import fetch_rss_headlines
from src.data.espn_injuries import fetch_injury_reports
from src.data.mlb_availability import fetch_roster_status
from scripts.evaluate_all import evaluate
from src.db.client import get_worker_db
from src.ingest.mlb_results import sync_mlb_results
from src.ingest.nhl_results import sync_nhl_results
from src.ingest.nba_results import sync_nba_results
from src.services.forecast_capture import capture
from src.services.forecast_grading import grade
from src.ingest.ncaaf_results import sync_ncaaf_results
from src.ingest.nfl_results import sync_nfl_results
from src.ingest.ncaaf_results import backfill_prop_results
from src.ingest.ncaaf_composites import derive_composites
from src.services.ncaaf_candidate_training import train as train_ncaaf_props


def archive(kind, payload):
    directory = Path(get_settings().raw_archive_dir) / kind
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%f')
    path = directory / f'{stamp}-{uuid.uuid4().hex}.json'
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('x') as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish only complete JSON; link is atomic and refuses overwrite.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return str(path)


async def renew_evaluation_lease(redis, key, token):
    while True:
        await asyncio.sleep(30)
        renewed = await redis.eval(
            "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],300) else return 0 end",
            1, key, token)
        if not renewed:
            raise RuntimeError('Evaluation lease lost')


async def evaluate_with_lease(redis, key, token):
    work = asyncio.create_task(evaluate())
    heartbeat = asyncio.create_task(renew_evaluation_lease(redis, key, token))
    try:
        done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            await heartbeat  # Lost leases must never publish a successful report.
        return await work
    finally:
        for task in (work, heartbeat):
            task.cancel()
        for task in (work, heartbeat):
            with suppress(asyncio.CancelledError, Exception):
                await task


async def evaluate_locked():
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    token = uuid.uuid4().hex
    key = 'calibration:evaluation_lock'
    try:
        if not await redis.set(key, token, nx=True, ex=300):
            return {'status': 'already_running'}
        try:
            from src.services.evaluation_status import latest, completed_today
            root = Path(get_settings().raw_archive_dir)
            previous, path = latest(root / 'calibration')
            if completed_today(previous, get_settings().supported_sports, datetime.now(timezone.utc)):
                return {'status': 'already_completed_today', 'report': path}
            run_id = uuid.uuid4().hex
            archive('evaluation-runs', {'run_id': run_id, 'status': 'running',
                'started_at': datetime.now(timezone.utc).isoformat()})
            try:
                report = await evaluate_with_lease(redis, key, token)
                destination = 'calibration' if report.get('status') == 'complete' else 'evaluation-partial'
                path = archive(destination, report)
                archive('evaluation-runs', {'run_id': run_id, 'status': report['status'],
                    'finished_at': datetime.now(timezone.utc).isoformat(), 'report': path})
                return {'status': report['status'], 'report': path}
            except BaseException as exc:
                archive('evaluation-runs', {'run_id': run_id, 'status': 'failed',
                    'finished_at': datetime.now(timezone.utc).isoformat(), 'error_type': type(exc).__name__})
                raise
        finally:
            await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
    finally:
        await redis.aclose()


@celery_app.task(name='fantasy.evaluate_models', soft_time_limit=1500, time_limit=1800)
def evaluate_models():
    return asyncio.run(evaluate_locked())


@celery_app.task(name='fantasy.validate_active_slate', soft_time_limit=240, time_limit=300)
def validate_active_slate():
    from scripts.validate_active_slate import validate
    report = asyncio.run(validate('http://api:8000', 'http://dashboard:3000', rounds=3))
    return {'status': report['status'], 'archive': archive('active-slate-validation', report)}


@celery_app.task(name='fantasy.sync_aggregate_props', soft_time_limit=480, time_limit=540)
def sync_aggregate_props():
    from src.ingest.aggregate_props import collect
    return asyncio.run(collect())


@celery_app.task(name='fantasy.archive_news', soft_time_limit=240, time_limit=300)
def archive_news():
    rows = asyncio.run(fetch_rss_headlines(get_settings().fantasy_news_rss_urls))
    return {'headlines': len(rows), 'archive': archive('news', rows)}


@celery_app.task(name='fantasy.archive_espn_injuries', soft_time_limit=240, time_limit=300)
def archive_espn_injuries():
    rows = asyncio.run(fetch_injury_reports())
    return {'reports': len(rows), 'archive': archive('espn_injuries', rows)}


@celery_app.task(name='fantasy.archive_mlb_availability', soft_time_limit=240, time_limit=300)
def archive_mlb_availability():
    rows = asyncio.run(fetch_roster_status())
    return {'reports': len(rows), 'archive': archive('mlb_availability', rows)}


@celery_app.task(name='fantasy.archive_football_availability', soft_time_limit=1500, time_limit=1800)
def archive_football_availability():
    from src.data.football_availability import collect
    async def run():
        async with get_worker_db() as db:
            return await collect(db)
    payload = asyncio.run(run())
    return {'games': len(payload['games']), 'archive': archive('football_availability', payload)}


@celery_app.task(name='fantasy.retry_team_ratings', soft_time_limit=900, time_limit=1200)
def retry_team_ratings():
    from src.services.team_rating_repair import retry_deferred
    async def run():
        async with get_worker_db() as db:
            return await retry_deferred(db)
    return asyncio.run(run())


@celery_app.task(name='fantasy.sync_mlb_results', soft_time_limit=900, time_limit=1200)
def mlb_results():
    async def run():
        async with get_worker_db() as db:
            return await sync_mlb_results(db)
    return asyncio.run(run())


@celery_app.task(name='fantasy.sync_nhl_results', soft_time_limit=900, time_limit=1200)
def nhl_results():
    async def run():
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        token = uuid.uuid4().hex
        key = 'calibration:nhl_results_lock'
        try:
            if not await redis.set(key, token, nx=True, ex=1800):
                return {'status': 'already_running'}
            try:
                async with get_worker_db() as db:
                    return await sync_nhl_results(db)
            finally:
                await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
        finally:
            await redis.aclose()
    return asyncio.run(run())


async def nba_results_locked():
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    token = uuid.uuid4().hex
    key = 'calibration:nba_results_lock'
    try:
        if not await redis.set(key, token, nx=True, ex=1800):
            return {'status': 'already_running'}
        try:
            async with get_worker_db() as db:
                return await sync_nba_results(db)
        finally:
            await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
    finally:
        await redis.aclose()


@celery_app.task(name='fantasy.sync_nba_results', soft_time_limit=900, time_limit=1200)
def nba_results():
    return asyncio.run(nba_results_locked())


@celery_app.task(name='fantasy.capture_forecasts', soft_time_limit=600, time_limit=900)
def capture_forecasts():
    async def run():
        async with get_worker_db() as db:
            payload = await capture(db)
        output = {'records': len(payload['records']), 'archive': archive('forecasts', payload)}
        # Independent transaction and archive. Research failures must not erase
        # a successful baseline capture or turn unsupported props actionable.
        try:
            from src.services.period_shadow_capture import capture as capture_period
            async with get_worker_db() as db:
                period = await capture_period(db)
            output['period_shadow'] = {'records': len(period['records']),
                'status': period['status'], 'archive': archive('period-shadow-forecasts', period)}
        except Exception as exc:
            output['period_shadow'] = {'status': 'failed', 'error_type': type(exc).__name__}
            archive('period-shadow-forecasts', output['period_shadow'])
        return output
    return asyncio.run(run())


@celery_app.task(name='fantasy.player_lab_prospective', soft_time_limit=240, time_limit=300)
def player_lab_prospective():
    from src.services.roster_stat_prospective import run
    async def execute():
        async with get_worker_db() as db:
            return await run(db)
    return asyncio.run(execute())


@celery_app.task(name='fantasy.grade_forecasts', soft_time_limit=600, time_limit=900)
def grade_forecasts():
    async def run():
        async with get_worker_db() as db:
            payload = await grade(db, Path(get_settings().raw_archive_dir) / 'forecasts')
        return {'counts': payload['counts'], 'archive': archive('grading', payload)}
    return asyncio.run(run())


@celery_app.task(name='fantasy.sync_nfl_results', soft_time_limit=900, time_limit=1200)
def nfl_results():
    async def run():
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        token = uuid.uuid4().hex
        key = 'calibration:nfl_results_lock'
        try:
            if not await redis.set(key, token, nx=True, ex=1500):
                return {'status': 'already_running'}
            try:
                async with get_worker_db() as db:
                    return await sync_nfl_results(db)
            finally:
                await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
        finally:
            await redis.aclose()
    return asyncio.run(run())


@celery_app.task(name='fantasy.sync_ncaaf_results', soft_time_limit=900, time_limit=1200)
def ncaaf_results():
    async def run():
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        token = uuid.uuid4().hex
        key = 'calibration:ncaaf_results_lock'
        try:
            if not await redis.set(key, token, nx=True, ex=1800):
                return {'status': 'already_running'}
            try:
                async with get_worker_db() as db:
                    return await sync_ncaaf_results(db)
            finally:
                await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
        finally:
            await redis.aclose()
    return asyncio.run(run())


@celery_app.task(name='fantasy.expand_ncaaf_props', soft_time_limit=1500, time_limit=1800)
def expand_ncaaf_props():
    async def run():
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        token = uuid.uuid4().hex
        key = 'calibration:ncaaf_results_lock'
        try:
            if not await redis.set(key, token, nx=True, ex=2100):
                return {'status': 'already_running'}
            try:
                async with get_worker_db() as db:
                    derived = await derive_composites(db)
                    await db.commit()
                    result = await backfill_prop_results(db)
                async with get_worker_db() as db:
                    report = await train_ncaaf_props(db)
                return {**result, 'existing_history_composites': derived,
                        'research_report': archive('prop-research', report),
                        'serving_parameters_changed': False}
            finally:
                await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)
        finally:
            await redis.aclose()
    return asyncio.run(run())
