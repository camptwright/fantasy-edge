from src.services.independent_football_results import compare, crosswalk
from tests.test_nfl_results import box


def inputs():
    summary = box()
    summary['header']['competitions'][0].update(date='2025-09-05T00:20:00Z',
        competitors=[{'homeAway': 'home', 'score': '7'}, {'homeAway': 'away', 'score': '3'}])
    schedule = {'game_id': 'g', 'espn': '42', 'gameday': '2025-09-04', 'home_score': 7, 'away_score': 3}
    return summary, schedule, [{'player_id': 'gsis', 'passing_yards': -3, 'receptions': 0}], {'gsis': '123'}


def test_crosswalk_conflicts_are_not_name_matched():
    rows = [{'gsis_id': 'a', 'espn_id': '1'}, {'gsis_id': 'b', 'espn_id': '1'},
            {'gsis_id': 'c', 'espn_id': '2'}, {'gsis_id': 'c', 'espn_id': '2'}]
    assert crosswalk(rows) == {'c': '2'}


def test_explicit_match_does_not_turn_missing_category_into_zero():
    result = compare(*inputs())
    assert result['counts'] == {'matched': 1, 'missing_espn': 1}
    assert not result['ready']


def test_wrong_date_score_and_identity_remain_blockers():
    summary, schedule, rows, ids = inputs()
    schedule['home_score'] = 8; schedule['gameday'] = '2025-09-05'
    report = compare(summary, schedule, rows, {})
    assert {'independent_final_score_mismatch', 'event_date_mismatch', 'unmapped_player_rows'} <= set(report['blockers'])


def test_disagreement_not_missing_evidence():
    summary, schedule, rows, ids = inputs()
    rows[0]['passing_yards'] = 3
    assert compare(summary, schedule, rows, ids)['counts']['mismatch'] == 1
