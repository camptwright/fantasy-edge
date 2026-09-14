from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from src.ingest.nfl_results import parse_boxscore, sync_nfl_results


def box():
    category = {'name': 'passing', 'keys': ['completions/passingAttempts', 'passingYards',
        'passingTouchdowns', 'interceptions'], 'athletes': [
        {'athlete': {'id': '123'}, 'stats': ['0/2', '-3', '0', '1']}]}
    return {'header': {'competitions': [{'id': '42', 'status': {'type': {'completed': True}}}]},
            'boxscore': {'players': [{'statistics': [category]}, {'statistics': [deepcopy(category)]}]}}


def test_explicit_zero_negative_yards_and_merge():
    result = parse_boxscore(box(), '42')['123']
    assert result == {'passing_completions': 0, 'passing_attempts': 2,
                      'passing_yards': -3, 'passing_touchdowns': 0, 'passing_interceptions': 1}
    assert 'rushing_yards' not in result
    assert 'pass_rush_yards' not in result


def test_explicit_fumbles_lost_only_no_absence_zero():
    payload = box()
    assert 'fumbles_lost' not in parse_boxscore(payload, '42')['123']
    payload['boxscore']['players'][0]['statistics'].append({'name': 'fumbles',
        'keys': ['fumbles', 'fumblesLost', 'fumblesRecovered'],
        'athletes': [{'athlete': {'id': '123'}, 'stats': ['1', '0', '0']}]})
    assert parse_boxscore(payload, '42')['123']['fumbles_lost'] == 0
    payload['boxscore']['players'][0]['statistics'][-1]['athletes'][0]['stats'][1] = '-1'
    with pytest.raises(ValueError):
        parse_boxscore(payload, '42')


def test_skip_explicit_team_aggregate_only():
    payload = box()
    row = {'athlete': {'id': '-6455', 'displayName': ' Team'}, 'stats': ['0/1', '0', '0', '0']}
    payload['boxscore']['players'][0]['statistics'][0]['athletes'].append(row)
    assert set(parse_boxscore(payload, '42')) == {'123'}
    row['athlete']['displayName'] = 'Unknown Player'
    with pytest.raises(ValueError):
        parse_boxscore(payload, '42')


@pytest.mark.parametrize('mutation', ['event', 'final', 'short', 'nan', 'conflict', 'pair', 'missing_team'])
def test_reject_ambiguous_payload(mutation):
    payload = box()
    row = payload['boxscore']['players'][0]['statistics'][0]['athletes'][0]
    if mutation == 'event':
        payload['header']['competitions'][0]['id'] = '43'
    elif mutation == 'final':
        payload['header']['competitions'][0]['status']['type']['completed'] = False
    elif mutation == 'short':
        row['stats'].pop()
    elif mutation == 'nan':
        row['stats'][1] = 'NaN'
    elif mutation == 'conflict':
        row['stats'][1] = '12'
    elif mutation == 'pair':
        row['stats'][0] = '3/2'
    else:
        payload['boxscore']['players'].pop()
    with pytest.raises(ValueError):
        parse_boxscore(payload, '42')


def test_targets_kicking_composites_and_dnp():
    payload = box()
    categories = payload['boxscore']['players'][0]['statistics']
    for name, keys, stats in [
        ('rushing', ['rushingYards'], ['5']),
        ('receiving', ['receivingTargets', 'receptions'], ['3', '0']),
        ('kicking', ['fieldGoalsMade/fieldGoalAttempts', 'extraPointsMade/extraPointAttempts',
                     'totalKickingPoints'], ['2/3', '1/1', '7'])]:
        categories.append({'name': name, 'keys': keys, 'athletes': [
            {'athlete': {'id': '123'}, 'stats': stats},
            {'athlete': {'id': '999'}, 'stats': stats, 'didNotPlay': True}]})
    result = parse_boxscore(payload, '42')
    assert '999' not in result
    assert result['123']['pass_rush_yards'] == 2
    assert result['123']['targets'] == 3
    assert result['123']['fg_made'] == 2
    assert result['123']['xp_made'] == 1


@pytest.mark.asyncio
async def test_nfl_delegates_to_shared_repair():
    db = AsyncMock()
    with patch('src.ingest.nfl_results.sync_football_results', new_callable=AsyncMock, return_value={'games': 0}) as repair:
        assert await sync_nfl_results(db) == {'games': 0}
        repair.assert_awaited_once_with(db, 'nfl', 40)
