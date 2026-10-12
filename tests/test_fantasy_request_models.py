import asyncio
import pytest
from fastapi import HTTPException
from src.services.fantasy_request_models import ModelRequests


async def test_concurrent_reads_share_generation_but_not_mutable_results():
    requests = ModelRequests()
    calls = 0
    async def generate():
        nonlocal calls
        calls += 1
        await asyncio.sleep(.01)
        return {'players': []}
    a, b = await asyncio.gather(requests.get('league', generate), requests.get('league', generate))
    a['players'].append('modified')
    assert b == {'players': []} and calls == 1
    await requests.get('league', generate)
    assert calls == 2  # No stale decisions survive a completed request.


async def test_disconnect_does_not_cancel_shared_generation_and_capacity_is_bounded():
    requests = ModelRequests(capacity=1)
    started, finish = asyncio.Event(), asyncio.Event()
    async def generate():
        started.set()
        await finish.wait()
        return {'ok': True}
    first = asyncio.create_task(requests.get('a', generate))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(HTTPException) as error:
        await requests.get('b', generate)
    assert error.value.status_code == 503
    finish.set()
    assert await requests.get('a', generate) == {'ok': True}


async def test_fallback_inputs_use_one_readonly_snapshot_across_concurrent_ingestion(db,monkeypatch):
    from collections import Counter
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.db import client
    from src.api import performance
    from src.services import fantasy_request_models as service, fantasy_read_model, fantasy_decision_models
    monkeypatch.setattr(service,'requests',ModelRequests())
    monkeypatch.setattr(performance,'fantasy_reads',Counter())
    async def sessions():
        async with AsyncSession(bind=db.bind) as owned:
            yield owned
    monkeypatch.setattr(client,'get_db',sessions)
    async def miss(owned,league_id):
        # The cache lookup itself establishes the transaction snapshot.
        await owned.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))
        return None
    monkeypatch.setattr(fantasy_read_model,'read',miss)
    async def generate(owned,league_id,**options):
        assert await owned.scalar(text('SHOW transaction_isolation'))=='repeatable read'
        assert await owned.scalar(text('SHOW transaction_read_only'))=='on'
        before=await owned.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))
        from src.models.facts import Game
        db.add(Game(sport='nfl', season=2026, status='scheduled'))
        await db.commit()
        after=await owned.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))
        assert before==after
        assert await db.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))>after
        await db.rollback()
        return {'revision':after}
    monkeypatch.setattr(fantasy_decision_models,'build',generate)
    first=await service.build(None,'test')
    second=await service.build(None,'test')
    assert second['revision']>first['revision']  # New requests see committed updates.
    assert performance.fantasy_reads=={'checkpoint_miss':2,'generated':2}


async def test_cache_hits_and_generation_failures_are_counted_without_entity_labels(db,monkeypatch):
    from collections import Counter
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.db import client
    from src.api import performance
    from src.services import fantasy_request_models as service, fantasy_read_model, fantasy_decision_models
    monkeypatch.setattr(service,'requests',ModelRequests())
    monkeypatch.setattr(performance,'fantasy_reads',Counter())
    async def sessions():
        async with AsyncSession(bind=db.bind) as owned:yield owned
    monkeypatch.setattr(client,'get_db',sessions)
    async def cached(*args):return {'status':'candidate'}
    monkeypatch.setattr(fantasy_read_model,'read',cached)
    assert await service.build(None,'private-league')=={'status':'candidate'}
    async def fails(*args,**kwargs):raise ValueError('synthetic failure')
    monkeypatch.setattr(fantasy_decision_models,'build',fails)
    with pytest.raises(ValueError,match='synthetic failure'):
        await service.build(None,'private-league',include_catalog=True)
    assert performance.snapshot()['fantasy_reads']=={
        'checkpoint_hit':1,'custom_request':1,'generation_failed':1}
    with pytest.raises(ValueError):performance.record_fantasy_read('private-league')
