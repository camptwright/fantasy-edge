from types import SimpleNamespace

from src.services.forecast_grading import unresolved_evidence


def record(game='g', player='p', market='receptions', kind='player'):
    return {'game_id': game, 'player_id': player, 'market': market, 'kind': kind}


def test_missing_categories_are_not_zeros_or_dnps():
    games = {'g': SimpleNamespace(sport='ncaaf', espn_event_id='123')}
    rows = [record(), record(), record(player='other'), record(game='empty'), record(kind='team')]
    result = unresolved_evidence(rows, games, {('p', 'g', 'rushing_yards'): 30})
    assert result['unique_outcomes'] == 4
    assert result['counts'] == {'missing_stat_with_other_player_results': 1,
        'no_player_results': 1, 'no_game_player_results': 1, 'missing_team_score': 1}
    r = next(r for r in result['items'] if r['reason'] == 'missing_stat_with_other_player_results')
    assert r['available_player_stats'] == ['rushing_yards']
    assert r['espn_event_id'] == '123'
    assert 'outcome' not in r


def test_aliases_and_model_duplicates_are_one_gap():
    result = unresolved_evidence([record(market='ints_thrown'), record(market='passing_interceptions')], {}, {})
    assert result['unique_outcomes'] == 1


def test_evidence_payload_bounded_but_counts_complete():
    result = unresolved_evidence([record(player=str(i)) for i in range(250)], {}, {})
    assert len(result['items']) == 200
    assert result['unique_outcomes'] == 250
    assert result['truncated']
