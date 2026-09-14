from types import SimpleNamespace
import fakeredis.aioredis
from src.services.odds_pacing import reserve, record_headers, status


def test_nfl_window_matches_collector_and_preserves_quota_guard():
    from datetime import datetime, timedelta, timezone
    from src.services.odds_pacing import apply_nfl_window
    now = datetime.now(timezone.utc)
    def report(reason='due'):
        return {'nfl_props_priority': True, 'sports': [{'sport': 'nfl', 'reason': reason}]}
    assert apply_nfl_window(report(), now+timedelta(hours=3), now)['sports'][0]['reason'] == 'outside_refresh_window'
    assert apply_nfl_window(report(), now+timedelta(hours=2), now)['sports'][0]['reason'] == 'due'
    assert apply_nfl_window(report(), None, now)['sports'][0]['reason'] == 'no_scheduled_game'
    assert apply_nfl_window(report('quota_guard'), None, now)['sports'][0]['reason'] == 'quota_guard'


async def test_reservation_prevents_duplicate_calls_and_reports_cooldown():
    settings = SimpleNamespace(odds_api_key='fake', supported_sports=['nfl', 'nhl'],
        odds_api_quota_floor=50, odds_api_season_months={'nfl': list(range(1, 13)), 'nhl': []})
    async with fakeredis.aioredis.FakeRedis() as redis:
        assert await reserve(redis, settings, 'nfl')
        assert not await reserve(redis, settings, 'nfl')
        assert not await reserve(redis, settings, 'nhl')
        report = await status(redis, settings)
        assert [s['reason'] for s in report['sports']] == ['paced', 'offseason']
        assert report['telemetry'] == {}
        await redis.set('odds_api:quota_exhausted', '1', ex=100)
        assert (await status(redis, settings))['quota_blocked']


async def test_telemetry_handles_missing_and_malformed_headers():
    async with fakeredis.aioredis.FakeRedis() as redis:
        report = await record_headers(redis, {'x-requests-remaining': '42', 'x-requests-used': 'bad'}, 200)
        assert report['remaining'] == 42
        assert report['used'] is None
        assert report['last_request_cost'] is None
