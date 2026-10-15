from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.services.engine_coverage import attach_coverage, week_state

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def fixture_games():
    # Complete NFL membership: pairs of teams have one bye and 17 games each.
    return [SimpleNamespace(id=f'{a}-{w}', game_type='REG', week=w,
                            home_team_id=str(a), away_team_id=str(a + 1),
                            status='scheduled', game_time=NOW + timedelta(days=w))
            for a in range(0, 32, 2) for w in range(1, 19) if w != 7]


def player(status='OUT'):
    return {'player_id': 'a', 'nfl_team_id': '0', 'identity_status': 'exact', 'injury_status': status,
            'availability_observed_at': NOW.isoformat(),
            'engine': {'status': 'not_projected', 'generated_at': NOW.isoformat(), 'weeks': []}}


def test_complete_schedule_proves_bye_but_partial_schedule_does_not():
    p = player(None)
    attach_coverage([p], fixture_games(), {'complete': True}, 6, NOW)
    assert week_state(p, 7)['status'] == 'verified_bye'
    attach_coverage([p], fixture_games()[:-1], {'complete': True}, 6, NOW)
    assert week_state(p, 7)['points'] is None


def test_out_is_nearest_game_only_and_ir_applies_later():
    games = [g for g in fixture_games() if g.week >= 6]
    p = player()
    attach_coverage([p], games, {'complete': False}, 6, NOW)
    assert week_state(p, 6)['status'] == 'confirmed_unavailable'
    assert week_state(p, 8)['points'] is None
    p['injury_status'] = 'INJURY_RESERVE'
    attach_coverage([p], games, {'complete': False}, 6, NOW)
    assert week_state(p, 8)['status'] == 'confirmed_unavailable'


def test_omission_stale_report_or_unresolved_identity_do_not_prove_absence():
    for mutate in (lambda p: p.update(injury_status='QUESTIONABLE'),
                   lambda p: p.update(identity_status='unresolved'),
                   lambda p: p.update(availability_observed_at=(NOW - timedelta(days=2)).isoformat()),
                   lambda p: p.update(availability_observed_at=(NOW + timedelta(hours=1)).isoformat()),
                   lambda p: p['engine'].update(generated_at=(NOW - timedelta(hours=4)).isoformat())):
        p = player()
        mutate(p)
        attach_coverage([p], fixture_games(), {'complete': True}, 6, NOW)
        assert week_state(p, 6)['points'] is None


def test_existing_finite_engine_week_is_preserved():
    p = player('IR')
    p['engine'].update(status='research', weeks=[{'week': 6, 'points': 12.5}])
    attach_coverage([p], fixture_games(), {'complete': True}, 6, NOW)
    assert week_state(p, 6) == {'status': 'projected', 'points': 12.5}


def test_conflicting_game_report_withholds_absence_zero():
    p = player('OUT')
    p['game_availability'] = {'status': 'reported_questionable', 'reports': [{'status': 'Questionable'}]}
    attach_coverage([p], [g for g in fixture_games() if g.week >= 6], {'complete': False}, 6, NOW)
    assert week_state(p, 6)['points'] is None
