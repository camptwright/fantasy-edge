from src.services.fantasy_locks import lineup
from src.services.fantasy_values import availability_flag
from src.services.workspace_player_evidence import availability_evidence


def test_locked_lineup_excludes_alias_absences_and_doubtful_without_excluding_questionable():
    base = {'player_id': 'a', 'name': 'A', 'position': 'WR', 'decision_points': 20, 'locked': False}
    backup = {**base, 'player_id': 'b', 'name': 'B', 'decision_points': 10}
    for designation in ('INJURY_RESERVE', 'PUP-R', 'O', 'D', 'SUS', 'INACTIVE'):
        result = lineup([{**base, 'injury_status': designation}, backup], ['WR'], ['a'])
        assert result['lineup'][0]['player_id'] == 'b'
    result = lineup([{**base, 'injury_status': 'Q'}, backup], ['WR'], ['a'])
    assert result['lineup'][0]['player_id'] == 'a'


def test_value_and_presentation_statuses_share_aliases_without_claiming_clearance():
    for designation in ('INJURY_RESERVE', 'PUP-R', 'O', 'D', 'SUS', 'INACTIVE'):
        p = {'position': 'RB', 'injury_status': designation}
        assert availability_flag(p)
        assert availability_evidence(p) == 'reported_restriction_requires_review'
    for designation in ('ACTIVE', 'Healthy', 'NORMAL'):
        p = {'position': 'RB', 'injury_status': designation}
        assert not availability_flag(p)
        assert availability_evidence(p) == 'no_restriction_reported_not_game_clearance'
