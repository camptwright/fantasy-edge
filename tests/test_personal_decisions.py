from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import copy
import pytest

from src.services.personal_decisions import freeze, grade_participant, request_key, create, history, InvalidDecision
from src.services.fantasy_score_history import scoring_hash
from src.services.forecast_evidence import digest

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def fixture(action='start'):
    gid = str(uuid4())
    kickoff = NOW + timedelta(hours=5)
    game = SimpleNamespace(id=gid, status='scheduled', season=2026, week=6, game_time=kickoff)
    scoring = {'rec': 1}
    league = SimpleNamespace(league_id='L', platform='sleeper', season='2026', scoring_settings=scoring, raw={})
    def p(pid, position='WR'):
        return {'player_id': pid, 'name': pid, 'position': position, 'decision_points': 10,
                'identity_status': 'exact', 'canonical_player_id': str(uuid4()), 'locked': False,
                'week_game_status': 'scheduled', 'ros': {'full_ros_value': 110},
                'next_games': [{'id': gid, 'week': 6, 'kickoff': kickoff.isoformat()}]}
    data = {'status': 'candidate', 'league_id': 'L', 'week': 6, 'generated_at': NOW.isoformat(),
            'coverage': {'stale_inputs': False}, 'scoring_contract_hash': scoring_hash(scoring),
            'players': [p('mine'), p('other'), p('free')], 'roster_positions': ['WR', 'BN'],
            'rosters': [{'roster_id': 1, 'is_mine': True, 'player_ids': ['mine']},
                        {'roster_id': 2, 'is_mine': False, 'player_ids': ['other']}], 'recipe_version': 'v1'}
    request = {'request_id': str(uuid4()), 'generated_at': NOW.isoformat(), 'action': action,
               'player_ids': ['mine'], 'counterparty_player_ids': [], 'note': 'My reasoning'}
    if action == 'pickup':
        request['player_ids'] = ['free', 'mine']
    elif action == 'trade':
        request['counterparty_player_ids'] = ['other']
    return data, league, request, {gid: game}


@pytest.mark.parametrize('action', ['start', 'pickup', 'trade'])
def test_freezes_current_choices_and_expectations_without_mutating_inputs(action):
    data, league, request, games = fixture(action)
    previous = copy.deepcopy(data)
    record = freeze(data, league, request, games, now=NOW)
    assert data == previous and record['action'] == action
    assert record['participants'][0]['prediction'] == 10 and record['model_version'] == 'v1'
    assert record['scoring_hash'] == scoring_hash(record['scoring_contract'])
    assert record['id'] == request_key('L', request['request_id'])


@pytest.mark.parametrize('change', ['stale', 'timestamp', 'wrong_owner', 'duplicate', 'locked', 'identity', 'protected', 'missing_points', 'scoring', 'wrong_slot'])
def test_invalid_or_changed_decisions_are_rejected(change):
    data, league, request, games = fixture()
    p = data['players'][0]
    if change == 'stale': data['coverage']['stale_inputs'] = True
    elif change == 'timestamp': request['generated_at'] = (NOW-timedelta(seconds=1)).isoformat()
    elif change == 'wrong_owner': request['player_ids'] = ['other']
    elif change == 'duplicate': request['player_ids'] = ['mine', 'mine']
    elif change == 'locked': p['locked'] = True
    elif change == 'identity': p['identity_status'] = 'unresolved'
    elif change == 'protected': data['_protected'] = {'mine'}
    elif change == 'missing_points': p['decision_points'] = None
    elif change == 'scoring': league.scoring_settings = {'rec': .5}
    elif change == 'wrong_slot': data['roster_positions'] = ['QB', 'BN']
    with pytest.raises(InvalidDecision): freeze(data, league, request, games, now=NOW)


def test_pickup_ownership_and_trade_single_counterparty_validation():
    data, league, request, games = fixture('pickup')
    request['player_ids'] = ['other', 'mine']
    with pytest.raises(InvalidDecision): freeze(data, league, request, games, now=NOW)
    request['action'] = 'trade'; request['player_ids'] = ['mine']; request['counterparty_player_ids'] = ['free']
    with pytest.raises(InvalidDecision): freeze(data, league, request, games, now=NOW)


def result_fixture():
    data, league, request, games = fixture()
    record = freeze(data, league, request, games, now=NOW)
    game = next(iter(games.values())); game.status = 'final'
    result = SimpleNamespace(league_id='L', kind='scored_history', week=6,
        synced_at=game.game_time+timedelta(hours=30), payload={'schema_version': 1, 'season': '2026', 'week': 6,
            'scoring_contract': record['scoring_contract'], 'scoring_hash': record['scoring_hash'],
            'game_ids': [str(game.id)], 'points': {'mine': 0}})
    return record, record['participants'][0], game, result


def test_explicit_final_zero_is_graded_but_missing_player_never_is_zero():
    record, p, game, result = result_fixture()
    now = result.synced_at+timedelta(hours=1)
    outcome = grade_participant(record, p, game, result, now=now)
    assert outcome['status'] == 'graded' and outcome['actual'] == 0 and outcome['error'] == -10
    result.payload['points'] = {}
    outcome = grade_participant(record, p, game, result, now=now)
    assert outcome['status'] == 'missing_player_result' and outcome['actual'] is None


@pytest.mark.parametrize('change', ['wrong_contract', 'wrong_game', 'wrong_season', 'early_snapshot', 'future_snapshot', 'capture_after_kickoff'])
def test_grading_requires_final_exact_contract_and_game_evidence(change):
    record, p, game, result = result_fixture()
    now = result.synced_at+timedelta(hours=1)
    if change == 'wrong_contract': result.payload['scoring_contract'] = {'rec': .5}
    elif change == 'wrong_game': result.payload['game_ids'] = []
    elif change == 'wrong_season': result.payload['season'] = '2025'
    elif change == 'early_snapshot': result.synced_at = game.game_time+timedelta(hours=1)
    elif change == 'future_snapshot': result.synced_at = now+timedelta(hours=1)
    elif change == 'capture_after_kickoff': record['captured_at'] = (game.game_time+timedelta(minutes=1)).isoformat()
    outcome = grade_participant(record, p, game, result, now=now)
    assert outcome['status'] != 'graded' and outcome['actual'] is None


async def test_idempotent_retry_returns_original_even_after_checkpoint_expires():
    data, league, request, games = fixture()
    record = freeze(data, league, request, games, now=NOW)
    class DB:
        async def get(self, model, key): return SimpleNamespace(payload=record)
    assert await create(DB(), 'L', request, now=NOW+timedelta(days=1)) == record
    with pytest.raises(InvalidDecision): await create(DB(), 'L', {**request, 'note': 'Different request'})


async def test_durable_save_idempotency_and_league_scoped_history(db, monkeypatch):
    from uuid import UUID
    from src.models.facts import Game
    from src.models.sleeper import SleeperLeague, SleeperRoster
    from src.models.governance import ForecastArchive
    from src.services import fantasy_read_model
    data, league, request, games = fixture()
    game = next(iter(games.values()))
    db.add(SleeperLeague(league_id='L', platform='sleeper', sport='nfl', name='Test', season='2026',
        status='in_season', roster_positions=data['roster_positions'], settings={}, scoring_settings=league.scoring_settings, raw={}))
    for roster in data['rosters']:
        db.add(SleeperRoster(league_id='L', roster_id=roster['roster_id'], owner_id='test',
            players=roster['player_ids'], starters=roster['player_ids'], settings={}, reserve=[], taxi=[]))
    db.add(Game(id=UUID(str(game.id)), sport='nfl', season=2026, week=6, status='scheduled', game_time=game.game_time))
    await db.commit()
    async def read(*args): return data
    monkeypatch.setattr(fantasy_read_model, 'read', read)
    saved = await create(db, 'L', request, now=NOW)
    assert (await create(db, 'L', request, now=NOW+timedelta(days=1)))['id'] == saved['id']
    db.add(ForecastArchive(digest='f'*64, kind='fantasy_decision', payload={**saved, 'league_id': 'other'}))
    await db.commit()
    rows = await history(db, 'L', now=NOW)
    assert len(rows) == 1 and rows[0]['id'] == saved['id'] and rows[0]['outcomes'][0]['status'] == 'awaiting_final'
    with pytest.raises(InvalidDecision): await create(db, 'L', {**request, 'note': 'Conflicting retry'}, now=NOW)
