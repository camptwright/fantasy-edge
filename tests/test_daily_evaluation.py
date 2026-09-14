from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import fakeredis.aioredis
import pytest
from src.scheduler import calibration
from src.services.evaluation_status import status


def setup(monkeypatch, tmp_path, report):
    server = fakeredis.FakeServer()
    def client(*a, **k):
        redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
        async def release(script, count, key, token):
            if await redis.get(key) == token:
                if "expire" in script:
                    return await redis.expire(key, 300)
                return await redis.delete(key)
            return 0
        redis.eval = release  # fakeredis installed without Lua support
        return redis
    monkeypatch.setattr(calibration.Redis, 'from_url', client)
    monkeypatch.setattr(calibration, 'get_settings', lambda: SimpleNamespace(
        raw_archive_dir=str(tmp_path), redis_url='redis://test', supported_sports=['nfl']))
    evaluator = AsyncMock(return_value=report)
    monkeypatch.setattr(calibration, 'evaluate', evaluator)
    return evaluator


async def test_daily_success_survives_new_clients(monkeypatch, tmp_path):
    report = {'status': 'complete', 'completed_at': datetime.now(timezone.utc).isoformat(), 'sports': {'nfl': {}}}
    evaluator = setup(monkeypatch, tmp_path, report)
    assert (await calibration.evaluate_locked())['status'] == 'complete'
    assert (await calibration.evaluate_locked())['status'] == 'already_completed_today'
    assert evaluator.await_count == 1
    assert status(tmp_path, ['nfl'])['completed_today_utc']


async def test_partial_is_retryable_and_not_published_as_complete(monkeypatch, tmp_path):
    evaluator = setup(monkeypatch, tmp_path, {'status': 'partial', 'sports': {'nfl': {'status': 'failed'}}})
    assert (await calibration.evaluate_locked())['status'] == 'partial'
    assert (await calibration.evaluate_locked())['status'] == 'partial'
    assert evaluator.await_count == 2
    assert not (tmp_path/'calibration').exists()


async def test_exception_recorded_and_lock_released(monkeypatch, tmp_path):
    evaluator = setup(monkeypatch, tmp_path, None)
    evaluator.side_effect = RuntimeError('test')
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await calibration.evaluate_locked()
    assert evaluator.await_count == 2
    assert status(tmp_path, ['nfl'])['latest_attempt']['status'] == 'failed'


async def test_one_sport_failure_does_not_discard_others(monkeypatch):
    from contextlib import asynccontextmanager
    from scripts import evaluate_all
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: [2026])
    @asynccontextmanager
    async def worker_db():
        yield db
    monkeypatch.setattr(evaluate_all, 'get_worker_db', worker_db)
    monkeypatch.setattr(evaluate_all, 'get_settings', lambda: SimpleNamespace(supported_sports=['nfl','mlb']))
    monkeypatch.setattr(evaluate_all, 'run_backtest', AsyncMock(side_effect=[ValueError('test'), []]))
    monkeypatch.setattr(evaluate_all, 'run_prop_backtest', AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(evaluate_all, 'evaluate_sport_distributions', AsyncMock(return_value={}))
    result = await evaluate_all.evaluate()
    assert result['status'] == 'partial'
    assert result['sports']['nfl']['status'] == 'failed'
    assert result['sports']['mlb']['status'] == 'complete'


def test_dead_worker_does_not_remain_running_forever(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, None)
    calibration.archive('evaluation-runs', {
        'status': 'running',
        'started_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
    assert status(tmp_path, ['nfl'])['latest_attempt']['status'] == 'abandoned'


async def test_lost_lease_cancels_evaluation(monkeypatch):
    import asyncio
    cancelled = asyncio.Event()
    async def work():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def lost(*args):
        raise RuntimeError('Evaluation lease lost')
    monkeypatch.setattr(calibration, 'evaluate', work)
    monkeypatch.setattr(calibration, 'renew_evaluation_lease', lost)
    with pytest.raises(RuntimeError, match='lease lost'):
        await calibration.evaluate_with_lease(None, 'key', 'token')
    assert cancelled.is_set()
