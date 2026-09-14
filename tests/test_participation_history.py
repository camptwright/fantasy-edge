from copy import deepcopy
from datetime import datetime, timezone
import pytest
from src.ingest.participation import verified_reception_zeros
from src.ingest.result_identities import identities
from scripts.repair_history import completed_mlb_games
from src.ingest.result_identities import seed_participants
from src.models.identity import Player, PlayerExternalId
from sqlalchemy import select, func


def football():
    return {'boxscore': {'players': [{'team': {'id': '1'}, 'statistics': [
        {'name': 'rushing', 'athletes': [{'athlete': {'id': '10'}}]},
        {'name': 'receiving', 'keys': ['receptions'], 'totals': ['2'],
         'athletes': [{'athlete': {'id': '20'}, 'stats': ['2']}]},
        {'name': 'passing', 'keys': ['completions/passingAttempts'], 'totals': ['2/3']}]}]}}


def test_zero_requires_rushing_participation_and_independent_totals():
    payload = football()
    parsed = {'10': {'rushing_attempts': 1}, '20': {'receptions': 2}}
    evidence = verified_reception_zeros(payload, parsed)
    assert len(evidence) == 1 and evidence[0]['stat'] == 'receptions'
    assert 'receptions' not in parsed['10']  # helper does not mutate input
    for bad in ('missing_total', 'mismatch', 'passing_mismatch', 'duplicate', 'dnp'):
        p = deepcopy(payload)
        s = p['boxscore']['players'][0]['statistics']
        if bad == 'missing_total':
            s[1]['totals'] = []
        elif bad == 'mismatch':
            s[1]['totals'] = ['3']
        elif bad == 'passing_mismatch':
            s[2]['totals'] = ['1/3']
        elif bad == 'duplicate':
            s.append(deepcopy(s[1]))
        else:
            s[0]['athletes'][0]['didNotPlay'] = True
        assert verified_reception_zeros(p, parsed) == []
    assert verified_reception_zeros(payload, {'10': {'rushing_attempts': 0}}) == []
    assert verified_reception_zeros(payload, {'10': {'rushing_attempts': 1, 'receptions': 1}}) == []


def test_identity_is_provider_native_not_a_name_join():
    p = football()
    p['boxscore']['players'][0]['statistics'][0]['athletes'][0]['athlete']['displayName'] = 'Same Name'
    assert identities(p, 'ncaaf') == {'10': ('Same Name', None)}
    assert identities(p, 'nfl') == {}


def test_mlb_schedule_excludes_preseason_future_and_unfinished_preserves_doubleheaders():
    game = {'gamePk': 1, 'season': '2026', 'gameDate': '2026-05-01T18:00:00Z',
        'gameType': 'R', 'status': {'abstractGameState': 'Final', 'codedGameState': 'F'},
        'teams': {s: {'team': {'name': s, 'id': i}, 'score': 1} for i, s in enumerate(('home', 'away'))}}
    other = deepcopy(game)
    other.update(gamePk=2, gameDate='2026-05-01T23:00:00Z')
    spring, future, pending = deepcopy(game), deepcopy(game), deepcopy(game)
    spring.update(gamePk=3, gameType='S')
    future.update(gamePk=4, gameDate='2026-10-01T23:00:00Z')
    pending.update(gamePk=5, status={'abstractGameState': 'Live'})
    result = completed_mlb_games({'dates': [{'games': [game, other, spring, future, pending]}]},
                                 2026, datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert [g['gamePk'] for g in result] == [1, 2]
    resumed = {**game, 'gameDate': '2026-05-02T18:00:00Z', 'resumedFrom': game['gameDate']}
    result = completed_mlb_games({'dates': [{'games': [game, resumed]}]}, 2026,
                                 datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert len(result) == 1 and result[0]['gameDate'] == game['gameDate']
    conflicting = deepcopy(game)
    conflicting['teams']['home']['score'] = 10
    with pytest.raises(ValueError):
        completed_mlb_games({'dates': [{'games': [game, conflicting]}]}, 2026,
                            datetime(2026, 9, 8, tzinfo=timezone.utc))
    cancelled = {**game, 'status': {'abstractGameState': 'Final', 'codedGameState': 'C'}}
    assert completed_mlb_games({'dates': [{'games': [cancelled]}]}, 2026,
                               datetime(2026, 9, 8, tzinfo=timezone.utc)) == []


async def test_provider_identity_seed_idempotent_no_same_name_merge(db):
    db.add(Player(sport='ncaaf', full_name='Same Name'))
    await db.flush()
    p = football()
    p['boxscore']['players'][0]['statistics'][0]['athletes'][0]['athlete']['displayName'] = 'Same Name'
    parsed = {'10': {'rushing_attempts': 1}}
    assert await seed_participants(db, 'ncaaf', 'espn_ncaaf', p, parsed) == 1
    assert await seed_participants(db, 'ncaaf', 'espn_ncaaf', p, parsed) == 0
    assert await db.scalar(select(func.count()).select_from(Player)) == 2
    assert await db.scalar(select(func.count()).select_from(PlayerExternalId)) == 1
