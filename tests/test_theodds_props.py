from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.ingest.theodds_props import rows_for, select_player, _get, poll_nfl_props

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def payload():
    return {'bookmakers': [{'key': 'fanduel', 'markets': [{
        'key': 'player_pass_yds', 'last_update': NOW.isoformat(), 'outcomes': [
            {'name': 'Over', 'description': 'Test Player', 'point': 200.5, 'price': -110},
            {'name': 'Under', 'description': 'Test Player', 'point': 200.5, 'price': -115}]}]}]}


def test_pairs():
    assert rows_for(payload(), NOW) == [('Test Player', 'passing_yards', 200.5, -110, -115)]


@pytest.mark.parametrize('change', ['stale', 'future', 'book', 'unpaired', 'duplicate', 'bad_price', 'alternate'])
def test_rejects_unsafe_quotes(change):
    value = payload()
    book = value['bookmakers'][0]
    market = book['markets'][0]
    if change == 'stale':
        market['last_update'] = '2026-09-08T00:00:00Z'
    elif change == 'future':
        market['last_update'] = '2026-09-10T00:00:00Z'
    elif change == 'book':
        book['key'] = 'other'
    elif change == 'unpaired':
        market['outcomes'].pop()
    elif change == 'duplicate':
        market['outcomes'].append(deepcopy(market['outcomes'][0]))
    elif change == 'bad_price':
        market['outcomes'][0]['price'] = 0
    else:
        other = deepcopy(market['outcomes'][0])
        other['point'] = 201.5
        market['outcomes'].append(other)
    assert rows_for(value, NOW) == []


def test_identity_fails_closed():
    game = SimpleNamespace(home_team_id=1, away_team_id=2)
    player = SimpleNamespace(full_name='Test Player', current_team_id=1)
    assert select_player([player], 'Test Player', game) is player
    assert select_player([player, player], 'Test Player', game) is None
    assert select_player([player], 'test player', game) is None
    player.current_team_id = 3
    assert select_player([player], 'Test Player', game) is None


@pytest.mark.asyncio
async def test_http_failure_is_secret_free():
    response = httpx.Response(401, request=httpx.Request('GET', 'https://example.test?apiKey=SECRET'))
    client = AsyncMock()
    client.get.return_value = response
    settings = SimpleNamespace(odds_api_base_url='https://example.test', odds_api_key='SECRET', odds_api_quota_floor=10)
    with pytest.raises(RuntimeError, match='401') as exc:
        await _get(client, AsyncMock(), settings, '/events')
    assert 'SECRET' not in str(exc.value)


@pytest.mark.asyncio
async def test_floor_blocks_before_network(monkeypatch):
    import src.ingest.theodds_props as module
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        odds_api_key='test', odds_api_nfl_props_priority=True, odds_api_quota_floor=10))
    monkeypatch.setattr(module, 'is_quota_exhausted', AsyncMock(return_value=False))
    class Lock:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    redis = AsyncMock()
    redis.lock = lambda *args, **kwargs: Lock()
    redis.get.return_value = '{"remaining": 13}'
    client = AsyncMock()
    monkeypatch.setattr(module.httpx, 'AsyncClient', client)
    assert await poll_nfl_props(AsyncMock(), redis) == 0
    client.assert_not_called()
    redis.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_priority_pauses_non_nfl(monkeypatch):
    import src.ingest.theodds as module
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(odds_api_nfl_props_priority=True))
    db, redis = AsyncMock(), AsyncMock()
    assert await module.poll_team_markets(db, redis, sport='mlb') == 0
    db.execute.assert_not_called()
    redis.set.assert_not_called()
