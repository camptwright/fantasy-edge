import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.data.football_availability import parse
from src.services.injury_evidence import for_game, fresh_rows, snapshots

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


def game():
    return SimpleNamespace(id=uuid.uuid4(), sport='nfl', espn_event_id='123', game_time=NOW+timedelta(hours=6))


def payload(g, status='Out'):
    return {'header': {'competitions': [{'id': '123', 'date': g.game_time.isoformat(),
        'competitors': [{'id': '1'}, {'id': '2'}]}]}, 'injuries': [{'team': {'id': '1'},
        'injuries': [{'athlete': {'id': '45'}, 'status': status, 'date': NOW.isoformat()}]}]}


@pytest.mark.parametrize('status,held', [('Out', True), ('Doubtful', True), ('Questionable', False), ('Active', False)])
def test_game_risk_hold_is_not_confirmed_inactive(status, held):
    g = game()
    event = parse(payload(g, status), g, NOW)
    result = for_game({}, g, ['45'], {str(g.id): event}, NOW)['game_availability']
    assert result['hold_recommendation'] is held
    assert result['official_game_status_verified'] is False


def test_event_player_and_time_isolation():
    g = game()
    event = parse(payload(g), g, NOW)
    assert not for_game({}, g, ['46'], {str(g.id): event}, NOW)['game_availability']['hold_recommendation']
    other = game()
    assert for_game({}, other, ['45'], {str(g.id): event}, NOW)['game_availability']['status'] == 'not_collected'
    assert for_game({}, g, ['45'], {str(g.id): event}, NOW+timedelta(hours=2))['game_availability']['status'] == 'stale_game_evidence'
    assert for_game({}, g, ['45'], {str(g.id): event}, NOW-timedelta(seconds=1))['game_availability']['status'] == 'stale_game_evidence'
    g.game_time += timedelta(hours=1)
    assert for_game({}, g, ['45'], {str(g.id): event}, NOW)['game_availability']['status'] == 'kickoff_changed'


def test_missing_ncaaf_section_is_not_a_healthy_roster():
    g = game()
    g.sport = 'ncaaf'
    data = payload(g)
    del data['injuries']
    event = parse(data, g, NOW)
    result = for_game({}, g, ['45'], {str(g.id): event}, NOW)['game_availability']
    assert result['status'] == 'not_provided' and not result['hold_recommendation']
    data['injuries'] = []
    event = parse(data, g, NOW)
    assert for_game({}, g, ['45'], {str(g.id): event}, NOW)['game_availability']['status'] == 'no_player_report'


def test_wrong_event_and_unrelated_team_rejected():
    g = game()
    data = payload(g)
    data['header']['competitions'][0]['id'] = '456'
    with pytest.raises(ValueError):
        parse(data, g, NOW)
    data = payload(g)
    data['injuries'][0]['team']['id'] = '999'
    with pytest.raises(ValueError):
        parse(data, g, NOW)


def test_malformed_row_does_not_drop_valid_injury(tmp_path):
    valid = {'reported_at': NOW.isoformat(), 'observed_at': NOW.isoformat()}
    (tmp_path/'1.json').write_text(json.dumps([{}, valid]))
    assert fresh_rows(tmp_path, NOW) == [valid]


@pytest.mark.asyncio
async def test_labels_distinguish_unsupported_identity_and_stale(tmp_path):
    nfl, nc, mlb = [uuid.uuid4() for _ in range(3)]
    db = AsyncMock()
    links = [(SimpleNamespace(source='espn_nfl', external_id='45', player_id=nfl), 'nfl'),
             (SimpleNamespace(source='espn_ncaaf', external_id='46', player_id=nc), 'ncaaf')]
    db.execute.side_effect = [SimpleNamespace(all=lambda: [(nfl, 'nfl'), (nc, 'ncaaf'), (mlb, 'mlb')]),
                              SimpleNamespace(all=lambda: links)]
    old = (NOW-timedelta(hours=2)).isoformat()
    (tmp_path/'1.json').write_text(json.dumps([{'sport': 'nfl', 'observed_at': old, 'reported_at': old}]))
    result = await snapshots(db, [{'player_id': str(p)} for p in (nfl, nc, mlb)], tmp_path, NOW)
    assert result[str(nfl)]['status'] == 'stale_archive'
    assert result[str(nc)]['status'] == 'coverage_not_supported'
    assert result[str(mlb)]['status'] == 'missing_provider_identity'
