from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, TimeoutError

from src.api.auth import require_fantasy_token
from src.api.workspace_app import app
from src.db.client import get_db


@pytest.mark.parametrize('failure', [TimeoutError('secret'), DBAPIError('private SQL', {}, Exception('secret'))])
async def test_dependency_failures_are_retryable_and_redacted(failure):
    async def failing_db():
        raise failure
        yield  # async generator dependency
    app.dependency_overrides[require_fantasy_token] = lambda: None
    app.dependency_overrides[get_db] = failing_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            for path in ('/health/ready', '/api/v2/fantasy/leagues', '/api/v2/operations/runtime'):
                response = await client.get(path)
                assert response.status_code == 503
                assert response.headers['Cache-Control'] == 'no-store'
                assert response.headers['Retry-After'] == '2'
                assert 'secret' not in response.text and 'SQL' not in response.text
    finally:
        app.dependency_overrides.clear()


async def test_readiness_is_authenticated_and_rechecks_database():
    database = SimpleNamespace(execute=AsyncMock())
    app.dependency_overrides[get_db] = lambda: database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/health/ready')).status_code == 401
            assert (await client.get('/api/v2/operations/runtime')).status_code == 401
            database.execute.assert_not_awaited()
            app.dependency_overrides[require_fantasy_token] = lambda: None
            for _ in range(2):
                assert (await client.get('/health/ready')).json()['status'] == 'ready'
            assert database.execute.await_count == 2
    finally:
        app.dependency_overrides.clear()


async def test_real_preview_pool_is_read_only_bounded_and_recreated(db, monkeypatch):
    from src.api import workspace_app
    from tests.conftest import TEST_DB_URL
    from sqlalchemy import text
    monkeypatch.setattr(workspace_app, 'get_settings', lambda: SimpleNamespace(database_url=TEST_DB_URL))
    for _ in range(2):
        async with workspace_app.lifespan(app):
            async for session in app.dependency_overrides[get_db]():
                assert await session.scalar(text('SHOW default_transaction_read_only')) == 'on'
                assert await session.scalar(text('SHOW statement_timeout')) == '2s'
                with pytest.raises(DBAPIError):
                    await session.execute(text('DELETE FROM derived_checkpoints WHERE false'))
                await session.rollback()
                with pytest.raises(DBAPIError):
                    await session.execute(text('SELECT pg_sleep(3)'))
                await session.rollback()
                assert await session.scalar(text('SELECT 1')) == 1
        assert get_db not in app.dependency_overrides
