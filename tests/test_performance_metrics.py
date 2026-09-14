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
