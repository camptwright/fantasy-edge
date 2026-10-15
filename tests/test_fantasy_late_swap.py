from datetime import datetime, timezone

from src.services.availability_status import normalize_status, confirmed_absent
from src.services.fantasy_late_swap import plans

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def player(pid, **kw):
    return {'player_id': pid, 'name': pid, 'position': 'WR', 'points': 10, 'source': 'sleeper',
            'week_kickoff': '2026-10-18T17:00:00Z', 'week_game_status': 'scheduled', 'locked': False,
            'injury_status': None, **kw}


def test_aliases_and_legal_later_bench_contingency():
    assert normalize_status('injury reserve') == 'IR'
    assert confirmed_absent('INJURY_RESERVE') and confirmed_absent('PUP-R')
    roster = [player('starter', injury_status='Q', points=20, play_probability=.7),
              player('later', week_kickoff='2026-10-18T20:00:00Z', points=12),
              player('earlier', week_kickoff='2026-10-18T15:00:00Z', points=30),
              player('other_starter', points=40), player('ir', reserve_slot='IR', points=80),
              player('taxi', reserve_slot='Taxi', points=80), player('absent', injury_status='INJURY_RESERVE', points=99)]
    out = plans(roster, [{'slot': 'WR', 'player_id': 'starter'}, {'slot': 'FLEX', 'player_id': 'other_starter'}], now=NOW)
    assert len(out['plans']) == 1
    plan = out['plans'][0]
    assert plan['replacement_id'] == 'later' and plan['risk_adjusted_points'] == 17.6


def test_missing_scores_locks_wrong_positions_and_questionable_backups_withheld():
    starter = player('starter', injury_status='D')
    for backup in [player('b', points=None), player('b', locked=True), player('b', position='QB'),
                   player('b', injury_status='Q'), player('b', week_kickoff=None),
                   player('b', week_game_status='no_game_this_week'), player('b', game_availability_hold=True)]:
        out = plans([starter, backup], [{'slot': 'WR1', 'player_id': 'starter'}], now=NOW)
        assert not out['plans'] and out['blockers'][0]['reason'] == 'no_eligible_later_bench_projection'
    out = plans([player('starter', injury_status='Q', locked=True), player('b')], [{'slot': 'WR', 'player_id': 'starter'}], now=NOW)
    assert out['blockers'][0]['reason'] == 'starter_locked_or_unknown_kickoff'


def test_zero_is_a_valid_backup_and_no_probability_is_invented():
    out = plans([player('starter', injury_status='Q', points=None), player('b', position='TE', points=0)],
                [{'slot': 'FLEX', 'player_id': 'starter'}], now=NOW)
    assert out['plans'][0]['replacement_points'] == 0 and out['plans'][0]['risk_adjusted_points'] is None


def test_conflicting_starter_evidence_keeps_backup_but_withholds_expected_value():
    out=plans([player('starter',injury_status='Q',points=20,play_probability=.7,game_availability_hold=True),
               player('backup',points=12)], [{'slot':'WR','player_id':'starter'}],now=NOW)
    assert out['plans'][0]['replacement_id']=='backup'
    assert out['plans'][0]['replacement_points']==12
    assert out['plans'][0]['risk_adjusted_points'] is None
