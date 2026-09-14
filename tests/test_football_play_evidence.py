from copy import deepcopy
import pytest
from src.services.football_play_evidence import parse_evidence, FIELDS
from src.services.football_structured_pbp import reconcile
from tests.test_football_structured_pbp import inputs


def payload(player='10', category='passing'):
    base = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/1/competitions/1/plays/1'
    return {'$ref': base + f'/participants/{player}/statistics/0', 'play': {'$ref': base},
        'splits': {'id': '0', 'name': 'play', 'categories': [{'name': category, 'stats': [
            {'name': name, 'value': 0.0} for name in FIELDS[category]]}]}}


def test_explicit_per_play_values_and_zeroes():
    p = payload()
    p['splits']['categories'][0]['stats'][0]['value'] = 12.0
    assert parse_evidence(p, 'nfl', '1', '1', '10', 'passing')['passing_yards'] == 12


@pytest.mark.parametrize('failure', ['cumulative', 'wrong_player', 'wrong_event', 'private', 'missing', 'nan', 'duplicate'])
def test_reject_unsafe_evidence(failure):
    p = payload()
    if failure == 'cumulative': p['splits']['name'] = 'game'
    if failure == 'wrong_player': p['$ref'] = p['$ref'].replace('/10/', '/20/')
    if failure == 'wrong_event': p['play']['$ref'] = p['play']['$ref'].replace('/events/1/', '/events/2/')
    if failure == 'private': p['$ref'] = p['$ref'].replace('espn.com', 'espn.pvt')
    if failure == 'missing': p['splits']['categories'][0]['stats'].pop()
    if failure == 'nan': p['splits']['categories'][0]['stats'][0]['value'] = float('nan')
    if failure == 'duplicate': p['splits']['categories'][0]['stats'].append(deepcopy(p['splits']['categories'][0]['stats'][0]))
    with pytest.raises(ValueError):
        parse_evidence(p, 'nfl', '1', '1', '10', 'passing')


def test_penalty_requires_all_roles_before_adding_any_values():
    core, summary = inputs()
    core['items'][0]['isPenalty'] = True
    partial = {'1:10': payload()}
    report = reconcile(core, summary, '1', 'nfl', {}, partial)
    assert not report['period_candidates']
    partial['1:20'] = payload('20', 'receiving')
    report = reconcile(core, summary, '1', 'nfl', {}, partial)
    assert report['resolved_with_per_play_statistics'] == ['1']
    assert not report['serving_enabled']
