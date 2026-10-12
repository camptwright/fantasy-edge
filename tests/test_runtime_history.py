import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from src.models.governance import DerivedCheckpoint
from src.services import runtime_history as runtime
from src.services.forecast_evidence import digest


def test_history_is_bounded_and_legacy_shapes_recover():
    result = runtime.append_observation({'history': [{'at': str(i)} for i in range(400)]}, {'at': 'latest'})
    assert len(result['history']) == 288
    assert result['history'][-1] == result['latest'] == {'at': 'latest'}
    assert len(runtime.append_observation({'history': None}, {'at': 'new'})['history']) == 1


async def test_probes_redact_bad_upstream_and_check_readiness():
    def respond(request):
        if request.url.path == '/health/ready':
            return httpx.Response(503, json={'detail': 'secret'})
        return httpx.Response(200, json={'process_id': 'pid', 'routes': {}, 'token': 'secret'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        main = await runtime.api_probe(client, runtime.SERVICES['production_api'])
        preview = await runtime.api_probe(client, runtime.SERVICES['preview_api'])
    assert main['status'] == 'reachable'
    assert main['current_rss_bytes'] is None
    assert preview['status'] == 'unreachable_or_not_ready'
    assert 'secret' not in str((main, preview))


async def test_queue_buckets_are_read_only_and_clients_close(monkeypatch):
    pipe = AsyncMock()
    from unittest.mock import MagicMock
    pipe.llen = MagicMock()
    pipe.execute.return_value = list(range(8))
    pipe.__aenter__.return_value = pipe
    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)
    redis.__aenter__.return_value = redis
    monkeypatch.setattr(runtime.Redis, 'from_url', lambda *a, **kw: redis)
    for _ in range(2):
        result = await runtime.queue_probe()
        assert result['waiting'] == {'celery': 6, 'evaluation': 22}
    assert redis.__aexit__.await_count == 2
    assert pipe.llen.call_args_list[1].args == ('celery\x06\x163',)
    assert pipe.llen.call_count == 16


async def test_real_observations_survive_distinct_event_loops(db, monkeypatch):
    from tests.conftest import TEST_DB_URL
    from sqlalchemy import text
    revision = await db.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))
    monkeypatch.setattr(runtime, 'get_settings', lambda: SimpleNamespace(
        database_url=TEST_DB_URL, fantasy_api_token='private'))
    monkeypatch.setattr(runtime, 'queue_probe', AsyncMock(return_value={'status': 'unreachable', 'waiting': None}))
    original_client = httpx.AsyncClient
    def respond(request):
        return httpx.Response(200, json=({'status': 'ready'} if request.url.path == '/health/ready'
                                       else {'process_id': 'pid', 'routes': {}}))
    monkeypatch.setattr(runtime.httpx, 'AsyncClient', lambda **kw: original_client(
        transport=httpx.MockTransport(respond), **kw))
    # Each call creates and disposes its own engine, client and event loop.
    for _ in range(2):
        assert (await asyncio.to_thread(lambda: asyncio.run(runtime.collect())))['status'] == 'saved'
    report = await runtime.status(db)
    assert report['status'] == 'current'
    assert len(report['history']) == 2
    assert report['latest']['database']['status'] == 'reachable'
    assert report['latest']['queues']['status'] == 'unreachable'
    assert await db.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1')) == revision
    assert 'private' not in str(report)
    row = await db.get(DerivedCheckpoint, runtime.NAME)
    row.payload = {**row.payload, 'latest': {'at': '1900-01-01T00:00:00+00:00'}}
    row.digest = digest(row.payload)
    await db.commit()
    assert (await runtime.status(db))['status'] == 'stale'
    row.digest = 'wrong'
    await db.commit()
    assert (await runtime.status(db))['status'] == 'awaiting_observer'


async def test_missing_observer_is_unknown(db):
    assert (await runtime.status(db))['status'] == 'awaiting_observer'
