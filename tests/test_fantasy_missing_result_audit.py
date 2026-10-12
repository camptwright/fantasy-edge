from types import SimpleNamespace

from scripts.audit_fantasy_missing_results import classify


def audit(rows=(), ids=frozenset({'123'}), event='event'):
    return classify({'player_id': 'p', 'game_id': 'g', 'name': 'Player'},
        SimpleNamespace(id='g', espn_event_id='event', home_team_id='h', away_team_id='a'),
        SimpleNamespace(current_team_id=None), ids,
        {'provider': 'espn_nfl', 'game_id': 'g', 'event_id': event,
         'payload': {'header': {'competitions': [{'id': event,
             'status': {'type': {'completed': True}}}]},
             'boxscore': {'players': [{'statistics': [{'athletes': list(rows)}]}]}}})


def test_unknown_team_and_absence_are_not_mismatch_or_zero():
    result = audit()
    assert result['current_team_check'] == 'unknown'
    assert result['evidence'] == 'athlete_absent_from_boxscore'
    assert 'actual' not in result


def test_exact_identity_and_event_required():
    assert audit(ids=set())['evidence'] == 'missing_provider_identity'
    assert audit(ids={'123', '456'})['evidence'] == 'ambiguous_provider_identity'
    assert audit(event='other')['evidence'] == 'unverified_archive_binding'
    assert audit([{'athlete': {'id': '456'}}])['evidence'] == 'athlete_absent_from_boxscore'


def test_dnp_is_distinct_from_participant_and_conflicts_require_review():
    dnp = {'athlete': {'id': '123'}, 'didNotPlay': True}
    played = {'athlete': {'id': '123'}, 'stats': ['0']}
    assert audit([dnp])['evidence'] == 'explicit_dnp_rows_only'
    assert audit([played])['evidence'] == 'athlete_present_requires_stat_review'
    assert audit([dnp, played])['evidence'] == 'athlete_present_requires_stat_review'
