from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

from src.services.retention_pipeline import adapt, freeze, outcomes, projection_points
from src.services.retention_research import grade_frozen
from src.services.fantasy_score_history import scoring_hash

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_midweek_research_starts_at_next_complete_slate():
    from src.services.retention_pipeline import planning_weeks
    g=N(week=5,status='scheduled',game_time=NOW+timedelta(days=1))
    assert planning_weeks(5,[g],NOW,3)==[5,6,7]
    g.status='final'
    assert planning_weeks(5,[g],NOW,3)==[6,7,8]
    g.week=18
    assert planning_weeks(18,[g],NOW,3)==[]


def fixture():
    scoring = {'rush_yd': .1}
    league = N(league_id='l', season='2026', platform='sleeper', scoring_settings=scoring)
    players = [{'player_id': p, 'name': p, 'position': 'RB', 'team': 'GB'} for p in ('a', 'b')]
    lab = {'status': 'candidate', 'coverage': {'stale_inputs': False}, 'players': players,
        'recipe_version': 'v', 'roster_positions': ['RB'],
        'rosters': [{'is_mine': True, 'player_ids': ['a']}],
        'waivers': {'moves': [{'add_id': 'b', 'drop_id': 'a'}]}}
    snapshots = [N(league_id='l', week=w, kind='projections', synced_at=NOW,
        payload={'a': {'rush_yd': 50}, 'b': {'rush_yd': 70}}) for w in (6, 7)]
    games = [N(id=f'g{w}', sport='nfl', season=2026, week=w, game_type='REG',
        status='scheduled', game_time=NOW+timedelta(days=w), home_team_id='gb', away_team_id=f'other{w}') for w in (6, 7)]
    teams = [N(id='gb', nflverse_abbr='GB')]
    return lab, league, snapshots, games, teams


def test_freeze_real_week_specific_provider_inputs_and_immutable_identity():
    args = fixture()
    records, blockers = freeze(*args, [6, 7], NOW)
    assert blockers == {}
    record = records[0]
    assert record['forecast']['total_gain'] == 4
    assert record['player_games']['7']['b']['game_id'] == 'g7'
    later, _ = freeze(*args, [6, 7], NOW+timedelta(minutes=2))
    assert later[0]['id'] == record['id']  # do not overwrite same scenario
    args[0]['recipe_version'] = 'new-model'
    changed, _ = freeze(*args, [6, 7], NOW)
    assert changed[0]['id'] != record['id']


def test_never_repeat_last_available_week_or_assume_missing_stats_zero():
    args = fixture(); args[2].pop()
    records, blockers = freeze(*args, [6, 7], NOW)
    assert not records and blockers['missing_or_stale_week_projection'] == 2
    assert projection_points({'rush_yd': 50}, {'rush_yd': .1, 'rush_td': 6}, 'sleeper') is None
    assert projection_points({'_espn_applied_total': 0}, {}, 'espn') == 0
    assert projection_points({'_espn_applied_total': 10}, {'rush_yd': .1}, 'sleeper') is None


def test_future_observed_stale_and_started_game_rejected():
    for delta in (timedelta(seconds=1), -timedelta(hours=7)):
        args = fixture(); args[2][0].synced_at = NOW+delta
        assert not freeze(*args, [6, 7], NOW)[0]
    args = fixture(); args[3][0].game_time = NOW
    assert not freeze(*args, [6, 7], NOW)[0]


def test_absent_schedule_is_not_a_bye_and_ambiguous_team_is_not_bound():
    args = fixture(); args[3].pop()
    players, bindings, blockers, _ = adapt(*args, [6, 7], NOW)
    assert 7 not in players[0]['future_weeks']
    assert not bindings['7']
    args = fixture(); args[4].append(N(id='wrong', nflverse_abbr='GB'))
    assert not freeze(*args, [6], NOW)[0]


def test_final_archives_require_exact_rules_and_event_before_grading():
    args = fixture(); record = freeze(*args, [6, 7], NOW)[0][0]
    snapshots = []
    for g in args[3]:
        g.status = 'final'
        snapshots.append(N(kind='scored_history', league_id='l', week=g.week,
            synced_at=g.game_time+timedelta(days=2), payload={
                'schema_version': 1, 'season': '2026', 'week': g.week,
                'scoring_contract': args[1].scoring_settings,
                'scoring_hash': scoring_hash(args[1].scoring_settings),
                'game_ids': [g.id], 'points': {'a': 10, 'b': 4}}))
    result = outcomes(record, snapshots, args[3], NOW+timedelta(days=20))
    assert grade_frozen(record, result)['actual_gain'] == -12
    snapshots[0].payload['scoring_contract'] = {'rush_yd': .2}
    assert grade_frozen(record, outcomes(record, snapshots, args[3], NOW+timedelta(days=20)))['status'] == 'withheld'


def test_roster_incomplete_does_not_create_smaller_fake_roster():
    args = fixture(); args[0]['rosters'][0]['player_ids'].append('missing')
    assert freeze(*args, [6], NOW)[1] == {'unbound_roster': 1}


def test_cannot_capture_an_add_owned_by_another_team():
    args = fixture()
    args[0]['rosters'].append({'is_mine': False, 'player_ids': ['b']})
    assert freeze(*args, [6, 7], NOW)[0] == []


def test_postseason_event_cannot_be_bound_as_regular_week():
    args = fixture()
    args[3][0].game_type = 'POST'
    assert not freeze(*args, [6, 7], NOW)[0]


def test_latest_pointer_is_compact_and_replaceable(tmp_path):
    import hashlib
    import json
    from src.services.retention_pipeline import publish_latest
    report = {'league_id': 'l', 'season': '2026', 'forecast_count': 2,
              'grades': [{'id': 'a', 'status': 'withheld'}, {'id': 'b', 'status': 'withheld'}]}
    publish_latest(tmp_path, report)
    path = tmp_path/'latest'/(hashlib.sha256(b'l').hexdigest()+'.json')
    saved = json.loads(path.read_text())
    assert 'grades' not in saved
    assert saved['grade_counts'] == {'withheld': 2}
    report['forecast_count'] = 3
    publish_latest(tmp_path, report)
    assert json.loads(path.read_text())['forecast_count'] == 3
    assert len(list(path.parent.iterdir())) == 1
