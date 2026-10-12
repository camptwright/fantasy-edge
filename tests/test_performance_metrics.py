from types import SimpleNamespace
from src.api.performance import PerformanceMiddleware, samples, snapshot


async def test_metrics_are_bounded_and_do_not_store_query_values():
    samples.clear()
    async def app(scope, receive, send):
        scope['route'] = SimpleNamespace(path='/games/{game_id}')
        await send({'type': 'http.response.start', 'status': 200})
        await send({'type': 'http.response.body', 'body': b'{}'})
    async def send(message):
        pass
    middleware = PerformanceMiddleware(app)
    for _ in range(205):
        await middleware({'type': 'http', 'query_string': b'token=secret'}, None, send)
    result = snapshot()
    assert result['routes']['/games/{game_id}']['samples'] == 200
    assert result['routes']['/games/{game_id}']['max_response_bytes'] == 2
    assert 'secret' not in str(result)
    row = result['routes']['/games/{game_id}']
    assert row['oldest_sample_age_seconds'] >= row['newest_sample_age_seconds'] >= 0


def test_current_memory_is_distinct_from_peak_and_unknown_when_unavailable(monkeypatch):
    from src.api import performance
    monkeypatch.setattr(performance.sys, 'platform', 'linux')
    monkeypatch.setattr(performance.Path, 'read_text', lambda self: '200 100 0')
    monkeypatch.setattr(performance.os, 'sysconf', lambda key: 4096)
    assert performance.current_rss_bytes() == 409600
    monkeypatch.setattr(performance.Path, 'read_text', lambda self: 'invalid')
    assert performance.current_rss_bytes() is None
    monkeypatch.setattr(performance.sys, 'platform', 'darwin')
    assert performance.current_rss_bytes() is None


async def test_preview_diagnostics_require_auth_and_do_not_cache():
    from httpx import ASGITransport, AsyncClient
    from src.api.workspace_app import app
    from src.api.main import require_fantasy_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/operations/performance')).status_code == 401
        app.dependency_overrides[require_fantasy_token] = lambda: None
        try:
            for _ in range(2):
                response = await client.get('/operations/performance')
                assert response.status_code == 200
                assert response.headers['Cache-Control'] == 'no-store'
                assert response.json()['service'] == 'workspace-preview'
                assert 'current_rss_bytes' in response.json()
        finally:
            app.dependency_overrides.pop(require_fantasy_token)
