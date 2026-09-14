from unittest.mock import AsyncMock
from types import SimpleNamespace
from src.ingest.lines import record_prop_line
from src.utils.normalize import normalize_stat_type
from src.services.backtest import run_backtest
from src.services.backtest import _closing_lines_by_game
from src.services.prop_backtest import run_prop_backtest
from src.ingest.prop_events import resolve_prop_event
from src.data.providers.underdog_api import raw_lines_to_props


def test_interception_aliases_preserve_period():
    for alias in ('ints_thrown', 'passing_interceptions', 'interceptions_thrown'):
        assert normalize_stat_type(alias) == 'passing_interceptions'
        assert normalize_stat_type('1H ' + alias) == '1h_passing_interceptions'


async def test_dedup_query_is_scoped_to_game():
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(line=3, over_price_american=-110,
                                            under_price_american=-110)
    await record_prop_line(db, player_id=None, game_id=None, stat_type='hits',
                           line=3, over_price_american=-110, under_price_american=-110,
                           source='test')
    assert 'player_prop_lines.game_id IS NULL' in str(db.scalar.call_args.args[0])


async def test_untimed_game_is_not_evaluated():
    db = AsyncMock()
    class Result:
        def scalars(self): return self
        def all(self): return [SimpleNamespace(id=1, game_time=None)]
    class Lines:
        def scalars(self): return []
    db.execute.side_effect = [Result(), Lines()]
    assert await run_backtest(db, 'nfl', [2025]) == []


async def test_event_resolution_refuses_ambiguous_and_untimed_events():
    db = AsyncMock()
    class Result:
        def all(self): return [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    db.scalars.return_value = Result()
    event = {'full_team_names_title': 'Away @ Home', 'scheduled_at': '2026-09-05T12:00:00Z'}
    assert await resolve_prop_event(db, 'nfl', event) is None
    event['scheduled_at'] = '2026-09-05T12:00:00'
    assert await resolve_prop_event(db, 'nfl', event) is None


def test_provider_preserves_game_but_not_season_series():
    event = {'id': 1, 'sport_id': 'NFL'}
    appearance = {'id': 'a', 'player_id': 'p', 'match_id': 1, 'match_type': 'Game'}
    payload = {'games': [event], 'appearances': [appearance],
        'players': [{'id': 'p', 'first_name': 'Test', 'last_name': 'Player', 'sport_id': 'NFL'}],
        'over_under_lines': [{'stat_value': 10.5, 'over_under': {'category': 'player_prop',
            'appearance_stat': {'appearance_id': 'a', 'display_stat': 'Passing Yards'}}}]}
    assert raw_lines_to_props(payload)[0]['event'] == event
    appearance['match_type'] = 'Series'
    assert raw_lines_to_props(payload)[0]['event'] is None


async def test_history_quote_query_excludes_postkickoff_observations():
    db = AsyncMock()
    class Result:
        def scalars(self): return []
    db.execute.return_value = Result()
    await _closing_lines_by_game(db, [1])
    query = str(db.execute.call_args.args[0])
    assert 'team_market_lines.observed_at <= games.game_time' in query
    assert 'games.game_time IS NOT NULL' in query


async def test_prop_replay_does_not_load_history_without_linked_quotes():
    db = AsyncMock()
    class Result:
        def all(self): return []
    db.execute.return_value = Result()
    rows, exclusions = await run_prop_backtest(db, 'nfl')
    assert rows == {}
    assert exclusions == {'no_linked_settled_quotes': 1}
    assert db.execute.await_count == 1
