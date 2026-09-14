from copy import deepcopy
import pytest
from src.services.football_structured_pbp import athlete_id, reconcile
from tests.test_football_pbp_validation import fixture


def inputs():
    summary = fixture()
    plays = deepcopy(summary['drives']['previous'][0]['plays'])
    plays[0].update(type={'text': 'Pass Reception'}, statYardage=12,
        participants=[{'type': role, 'athlete': {'$ref':
            f'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2026/athletes/{pid}'},
            'stats': [{'name': 'passingYards', 'value': 999}]} for role, pid in [('passer', '10'), ('receiver', '20')]])
    core = {'$ref': 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/1/competitions/1/plays',
            'items': plays, 'count': 4, 'pageCount': 1, 'pageIndex': 1}
    return core, summary


def test_structured_yards_ignore_inline_game_totals_and_never_enable():
    core, summary = inputs()
    result = reconcile(core, summary, '1', 'nfl', {'10': {'passing_yards': 12}})
    assert not result['timeline_blockers']
    assert next(x for x in result['comparisons'] if x['stat'] == 'passing_yards')['state'] == 'matched'
    assert not result['serving_enabled']


def test_incomplete_page_wrong_event_and_mismatch():
    core, summary = inputs()
    core['count'] = 5
    result = reconcile(core, summary, '2', 'nfl', {'10': {'passing_yards': 13}})
    assert {'incomplete_core_page', 'wrong_core_event'} <= set(result['timeline_blockers'])
    assert next(x for x in result['comparisons'] if x['stat'] == 'passing_yards')['state'] == 'mismatch'


def test_penalty_not_assumed_to_count():
    core, summary = inputs()
    core['items'][0]['isPenalty'] = True
    result = reconcile(core, summary, '1', 'nfl', {'10': {'passing_yards': 12}})
    assert result['unresolved_plays']
    assert result['comparisons'][0]['state'] == 'missing_derived'


def test_private_or_wrong_league_identity_rejected():
    core, _ = inputs()
    participant = core['items'][0]['participants'][0]
    with pytest.raises(ValueError):
        athlete_id(participant, 'college-football')
    participant['athlete']['$ref'] = participant['athlete']['$ref'].replace('espn.com', 'espn.pvt')
    with pytest.raises(ValueError):
        athlete_id(participant, 'nfl')


def test_duplicate_sequences_use_checked_provider_order():
    core, summary = inputs()
    for play in core['items']:
        play['sequenceNumber'] = '1'
    assert not reconcile(core, summary, '1', 'nfl', {})['timeline_blockers']
