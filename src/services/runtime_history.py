"""Bounded cross-service observations, separate from prediction evidence.

Only writes one derived checkpoint. No Docker socket, provider access, Celery
dispatch, query text, task payloads or credentials in observations.
"""
import asyncio
from datetime import datetime, timezone
from time import monotonic

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config.settings import get_settings
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest

NAME = 'workspace-runtime-history'
RETENTION = 288
SERVICES = {'production_api': 'http://api:8000', 'preview_api': 'http://workspace-api:8000'}


async def api_probe(client, base):
    started = monotonic()
    try:
        response = await client.get(base + '/operations/performance')
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('routes'), dict) or not data.get('process_id'):
            raise ValueError('Invalid metrics')
        # Whitelist fields; never archive arbitrary upstream error bodies.
        result = {key: data.get(key) for key in (
            'process_id', 'started_at', 'current_rss_bytes', 'peak_rss_bytes')}
        routes = list(data['routes'].values())[:129]
        result.update(status='reachable', route_count=len(routes),
                      rolling_5xx=sum(r.get('server_errors', 0) for r in routes),
                      rolling_max_p95_ms=max((r.get('p95_ms', 0) for r in routes), default=None))
        if base == SERVICES['preview_api']:
            ready = await client.get(base + '/health/ready')
            ready.raise_for_status()
            if ready.json().get('status') != 'ready':
                raise ValueError('Invalid readiness')
        return {**result, 'probe_ms': round((monotonic()-started)*1000, 2)}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return {'status': 'unreachable_or_not_ready', 'probe_ms': round((monotonic()-started)*1000, 2)}


async def queue_probe():
    try:
        async with Redis.from_url(get_settings().redis_url, socket_connect_timeout=2,
                                  socket_timeout=2) as redis:
            # Kombu Redis transport's default priority buckets. Never consume jobs.
            keys = [queue + (f'\x06\x16{p}' if p else '')
                    for queue in ('celery', 'evaluation') for p in (0, 3, 6, 9)]
            async with redis.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.llen(key)
                lengths = await pipe.execute()
            return {'status': 'reachable', 'waiting': {
                'celery': sum(lengths[:4]), 'evaluation': sum(lengths[4:])}}
    except Exception:
        # Driver errors may include credentials; persist only the state.
        return {'status': 'unreachable', 'waiting': None}


async def database_probe(factory):
    started = monotonic()
    try:
        async with factory() as db:
            row = (await db.execute(text('''
                SELECT count(*) AS connections,
                       count(*) FILTER (WHERE state='active') AS active,
                       count(*) FILTER (WHERE wait_event_type='Lock') AS lock_waiters,
                       count(*) FILTER (WHERE state='idle in transaction') AS idle_in_transaction
                FROM pg_stat_activity
                WHERE datname=current_database() AND pid<>pg_backend_pid()
            '''))).mappings().one()
            return {'status': 'reachable', **dict(row), 'probe_ms': round((monotonic()-started)*1000, 2)}
    except Exception:
        return {'status': 'unreachable', 'probe_ms': round((monotonic()-started)*1000, 2)}


def append_observation(prior, observation):
    history = prior.get('history', []) if isinstance(prior, dict) else []
    if not isinstance(history, list):
        history = []
    return {'latest': observation, 'history': history[-(RETENTION-1):] + [observation]}


async def persist(db, observation):
    # Nonblocking lock: a second observer must not wait behind an unhealthy writer.
    if not await db.scalar(text('SELECT pg_try_advisory_xact_lock(79431803)')):
        return False
    old = await db.get(DerivedCheckpoint, NAME)
    prior = old.payload if old and digest(old.payload) == old.digest else {}
    payload = append_observation(prior, observation)
    values = {'name': NAME, 'payload': payload, 'digest': digest(payload),
              'updated_at': datetime.now(timezone.utc)}
    await db.execute(insert(DerivedCheckpoint).values(**values).on_conflict_do_update(
        index_elements=['name'], set_={k: v for k, v in values.items() if k != 'name'}))
    await db.commit()
    return True


async def collect():
    # Fresh engine and Redis client on every observation, safe across asyncio.run.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool,
        connect_args={'timeout': 3, 'server_settings': {'statement_timeout': '2000',
                                                     'lock_timeout': '1000'}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(timeout=3, headers={
                    'Authorization': 'Bearer ' + get_settings().fantasy_api_token}) as client:
                production, preview, queues, database = await asyncio.gather(
                    *(api_probe(client, url) for url in SERVICES.values()),
                    queue_probe(), database_probe(factory))
            observation = {'at': datetime.now(timezone.utc).isoformat(),
                           'production_api': production, 'preview_api': preview,
                           'queues': queues, 'database': database}
            async with factory() as db:
                saved = await persist(db, observation)
            return {'status': 'saved' if saved else 'observer_already_writing', 'at': observation['at']}
    finally:
        await engine.dispose()


async def status(db):
    row = await db.get(DerivedCheckpoint, NAME)
    if row is None or digest(row.payload) != row.digest:
        return {'status': 'awaiting_observer', 'history': []}
    try:
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(row.payload['latest']['at'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return {'status': 'invalid_observation', 'history': []}
    return {**row.payload, 'status': 'current' if 0 <= age <= 660 else 'stale',
            'age_seconds': round(age), 'scope':
            'Up to 288 five-minute snapshots, not continuous tracing. Queue counts exclude running/reserved jobs; '
            'zero waiting does not prove worker health. API 5xx/p95 values are rolling request windows, not interval totals. '
            'Database counts are point-in-time, not CPU or query-duration measurements. '
            'Observer freshness is not a declaration that every service is healthy.'}
