"""Exercise the scheduled transaction boundary, not just save() in isolation."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from src.models.governance import ForecastArchive
from tests.conftest import TEST_DB_URL


async def test_capture_task_persists_on_two_separate_event_loops(db, monkeypatch):
    from src.scheduler import calibration
    from src.services import paper_ledger, period_shadow_capture

    @asynccontextmanager
    async def sessions():
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    async def capture(session):
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        assert await session.scalar(text('SHOW transaction_read_only')) == 'on'
        return {'schema_version': 1, 'capture_id': uuid4().hex,
                'captured_at': datetime.now(timezone.utc).isoformat(), 'records': []}

    async def paper(session):
        assert await session.scalar(text('SHOW transaction_read_only')) == 'off'
        return {'status': 'ok'}

    async def period(session):
        return {'records': [], 'status': 'research'}

    monkeypatch.setattr(calibration, 'get_worker_db', sessions)
    monkeypatch.setattr(calibration, 'capture', capture)
    monkeypatch.setattr(calibration, 'archive', lambda *args: 'test-archive')
    monkeypatch.setattr(paper_ledger, 'capture', paper)
    monkeypatch.setattr(period_shadow_capture, 'capture', period)
    for _ in range(2):
        result = await asyncio.to_thread(calibration.capture_forecasts.run)
        assert result['paper_ledger']['status'] == 'ok'
        assert result['period_shadow']['status'] == 'research'
    assert await db.scalar(select(func.count()).select_from(ForecastArchive).where(ForecastArchive.kind=='forecasts')) == 2
    from src.services.forecast_evidence import capture_status
    assert (await capture_status(db))['status']=='current'
