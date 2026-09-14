from copy import deepcopy
from src.services.football_pbp_validation import audit


def fixture():
    plays = [{'id': str(i), 'sequenceNumber': str(i), 'period': {'number': i},
        'clock': {'displayValue': '15:00' if i == 1 else '0:00'}, 'homeScore': 0, 'awayScore': 0,
        'type': {'text': 'End of Game' if i == 4 else 'End Period'}, 'scoringPlay': False}
        for i in range(1, 5)]
    return {'header': {'competitions': [{'id': '1', 'status': {'type': {'completed': True}},
        'competitors': [{'homeAway': side, 'score': '0',
                         'linescores': [{'displayValue': '0'}]*4} for side in ('home', 'away')]}]},
        'drives': {'previous': [{'plays': plays}]}, 'scoringPlays': []}


def test_score_checks_do_not_claim_player_prop_validation():
    result = audit(fixture(), '1')
    assert result['timeline_checks_passed']
    assert not result['player_prop_ready'] and not result['serving_enabled']


def test_missing_period_final_score_and_wrong_event_fail_closed():
    p = fixture()
    p['drives']['previous'][0]['plays'].pop(1)
    assert 'missing_or_extra_period' in audit(p, '1')['timeline_blockers']
    assert not audit(fixture(), 'wrong')['timeline_checks_passed']
    p = fixture()
    p['header']['competitions'][0]['competitors'][0]['score'] = '7'
    assert 'final_score_mismatch' in audit(p, '1')['timeline_blockers']


def test_conflicting_duplicate_and_unlinked_score_fail_closed():
    p = fixture()
    duplicate = deepcopy(p['drives']['previous'][0]['plays'][0])
    duplicate['homeScore'] = 1
    p['drives']['previous'][0]['plays'].append(duplicate)
    assert 'conflicting_play_id' in audit(p, '1')['timeline_blockers']
    p = fixture()
    p['scoringPlays'] = [{'id': 'absent', 'scoringType': {'name': 'touchdown'}}]
    assert 'scoring_index_mismatch' in audit(p, '1')['timeline_blockers']


def test_malformed_and_overtime_are_not_accepted():
    assert not audit({}, '1')['timeline_checks_passed']
    p = fixture()
    p['drives']['previous'][0]['plays'][-1]['period']['number'] = 5
    assert 'overtime_or_period_rules_unvalidated' in audit(p, '1')['timeline_blockers']


def test_touchdown_order_is_play_order_not_a_scorer_identity():
    p = fixture()
    home = p['header']['competitions'][0]['competitors'][0]
    home['score'] = '6'
    home['linescores'] = [{'displayValue': str(x)} for x in (0, 6, 0, 0)]
    plays = p['drives']['previous'][0]['plays']
    for play in plays[1:]:
        play['homeScore'] = 6
    plays[1]['type']['text'] = 'Passing Touchdown'
    plays[1]['scoringPlay'] = True
    p['scoringPlays'] = [{'id': '2', 'scoringType': {'name': 'touchdown'}}]
    result = audit(p, '1')
    assert result['timeline_checks_passed']
    assert result['touchdown_play_ids_in_order'] == ['2']
    assert not result['player_prop_ready']
    p['scoringPlays'] = []
    assert 'touchdown_index_mismatch' in audit(p, '1')['timeline_blockers']
