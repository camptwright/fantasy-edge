"""Daily candidate evaluation and timestamped news archive.

Reports remain experimental. Serving probabilities never load these files.
"""
import asyncio
import json
import os
import uuid
from contextlib import suppress
from datetime import datetime, timezone, timedelta
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


def archive_capture(compact, bodies) -> str:
    """Raw mirror of the database form: create-only bodies by digest, then the compact capture."""
    from src.services.roster_stat_prospective import publish
    root = Path(get_settings().raw_archive_dir) / 'forecasts' / 'records'
    for key, body in bodies.items():
        publish(root / f'{key}.json', body)  # create-only: an existing body is the same content
    return archive('forecasts', compact)


def write_latest(directory: Path, payload) -> str:
    """Atomically replace `_latest.json` (mutable; never compressed or treated as history)."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / '_latest.json'
    temporary = directory / f'._latest-{uuid.uuid4().hex}.tmp'
    try:
        with temporary.open('x') as stream:
            json.dump(payload, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


def archive_grading(payload, change, *, keyframe_every=timedelta(hours=24)):
    """Delta every run; a full keyframe at most daily so replay from history stays short."""
    from src.utils import archive_io
    root = Path(get_settings().raw_archive_dir) / 'grading'
    out = {'archive': archive('grading/deltas', change), 'latest': write_latest(root, payload)}
    keyframes = archive_io.files(root)
    keyframes = [p for p in keyframes if not p.name.startswith('_')]
    last = datetime.strptime(keyframes[-1].name[:15], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc) if keyframes else None
    if last is None or datetime.now(timezone.utc) - last >= keyframe_every:
        out['keyframe'] = archive('grading', payload)
    return out


@celery_app.task(name='fantasy.archive_rosters', soft_time_limit=600, time_limit=660)
def archive_rosters():
    async def run():
        from src.services.roster_evidence import collect
        async with get_worker_db() as db:
            payload = await collect(db)
        verified = sum(r['status'] == 'verified_roster' for r in payload['teams'])
        from src.services.roster_evidence import drop_unchanged_payloads
        from src.utils import archive_io
        previous_files = archive_io.files(Path(get_settings().raw_archive_dir) / 'roster-evidence')
        try:
            previous = archive_io.read_json(previous_files[-1]) if previous_files else None
        except (OSError, ValueError):
            previous = None
        drop_unchanged_payloads(payload, previous)
        path = archive('roster-evidence', payload)
        if payload['teams'] and not verified:
            raise RuntimeError('All roster sources failed; failed evidence archived.')
        return {'teams': len(payload['teams']), 'verified': verified,
                'failed': len(payload['teams'])-verified, 'archive': path}
    return asyncio.run(run())


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
            from src.services.model_version import manifest
            evaluation_version=manifest()
            if completed_today(previous, get_settings().supported_sports, datetime.now(timezone.utc),evaluation_version):
                return {'status': 'already_completed_today', 'report': path}
            run_id = uuid.uuid4().hex
            archive('evaluation-runs', {'run_id': run_id, 'status': 'running',
                'started_at': datetime.now(timezone.utc).isoformat()})
            try:
                report = await evaluate_with_lease(redis, key, token)
                report.setdefault('serving_version_manifest',evaluation_version)
                if manifest()!=evaluation_version:
                    report={**report,'status':'partial','reason':'serving_configuration_changed_during_evaluation'}
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
        # capture deliberately opens a READ ONLY repeatable-read transaction.
        # Persist only after closing it, using a fresh worker-owned write session.
        async with get_worker_db() as db:
            from src.services.forecast_evidence import save, save_capture
            compact, bodies = await save_capture(db, payload)
            await save(db,'capture_status',{'capture_id':payload['capture_id'],
                'captured_at':payload['captured_at'],'records':len(payload['records']),
                'model_version':payload.get('model_version')})
            await db.commit()
        output = {'records': len(payload['records']), 'archive': archive_capture(compact, bodies)}
        from src.services.paper_ledger import capture as capture_paper
        async with get_worker_db() as db:
            output['paper_ledger'] = await capture_paper(db)
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


@celery_app.task(name='fantasy.college_lab_prospective', soft_time_limit=240, time_limit=300)
def college_lab_prospective():
    from src.services.college_prospective import execute
    return asyncio.run(execute())


@celery_app.task(name='fantasy.fantasy_prospective', soft_time_limit=240, time_limit=300)
def fantasy_prospective():
    from src.services.fantasy_prospective import execute
    return asyncio.run(execute())


@celery_app.task(name='fantasy.full_nfl_schedule', soft_time_limit=240, time_limit=300)
def full_nfl_schedule():
    from src.services.fantasy_schedule import sync
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc)
    async def execute():
        async with get_worker_db() as db:
            return await sync(db,now.year if now.month>=8 else now.year-1)
    return asyncio.run(execute())


@celery_app.task(name='fantasy.fantasy_scoring', soft_time_limit=540, time_limit=600)
def fantasy_scoring():
    from src.ingest.fantasy_scoring import sync
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc)
    async def execute():
        async with get_worker_db() as db:
            return await sync(db,now.year if now.month>=8 else now.year-1)
    return asyncio.run(execute())


@celery_app.task(name='fantasy.grade_forecasts', soft_time_limit=600, time_limit=900)
def grade_forecasts():
    async def run():
        from src.services.forecast_evidence import import_archives,save
        async with get_worker_db() as db:
            imported=await import_archives(db,Path(get_settings().raw_archive_dir)/'forecasts')
        if not imported['complete']:
            return {'status':'historical_evidence_import_pending',**imported}
        from src.services.forecast_checkpoint import refresh
        async with get_worker_db() as db:
            checkpoint=await refresh(db)
        async with get_worker_db() as db:
            payload = await grade(db)
        from src.services.forecast_evidence import save_grading
        async with get_worker_db() as db:
            change=await save_grading(db,payload)
            await db.commit()
        return {'counts': payload['counts'], 'cohort_checkpoint':checkpoint, **archive_grading(payload, change)}
    return asyncio.run(run())


@celery_app.task(name='fantasy.refresh_missing_results', soft_time_limit=600, time_limit=900)
def refresh_missing_results():
    async def run():
        from src.services.missing_result_queue import rebuild
        from src.services.forecast_evidence import save
        async with get_worker_db() as db:
            payload=await rebuild(db)
        async with get_worker_db() as db:
            await save(db,'missing_results',payload)
            await db.commit()
        return {'total':payload['total'],'generated_at':payload['generated_at']}
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
