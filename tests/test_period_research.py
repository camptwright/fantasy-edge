from copy import deepcopy
from src.services.period_history import validate_game, FIELDS
from src.services.period_candidates import evaluate


def fixture():
    schedule = {'game_id': 'g', 'season': 2024, 'gameday': '2024-09-01', 'home_score': 0, 'away_score': 0}
    plays = [{'play_deleted': 0, 'order_sequence': q, 'play_id': q, 'qtr': q,
        'quarter_seconds_remaining': 900 if q == 1 else 0,
        'play_type_nfl': 'GAME_START' if q == 1 else 'END_GAME' if q == 4 else 'END_QUARTER',
        'total_home_score': 0, 'total_away_score': 0} for q in range(1, 5)]
    box = [{'player_id': 'p', 'position': 'WR', **dict.fromkeys(FIELDS, 0),
        'rushing_tds': 0, 'receiving_tds': 0, 'special_teams_tds': 0, 'def_tds': 0}]
    return plays, box, schedule


def test_explicit_final_zero_and_all_quarters_required():
    plays, box, schedule = fixture()
    result = validate_game(plays, box, schedule)
    assert result['families']['receptions']['reconciled']
    assert all(r['value'] == 0 for r in result['labels'])
    plays.pop(1)
    assert not validate_game(plays, box, schedule)['labels']


def test_missing_box_field_and_mismatch_block_family():
    plays, box, schedule = fixture()
    box[0]['receptions'] = 1
    result = validate_game(plays, box, schedule)
    assert not result['families']['receptions']['reconciled']
    assert not any(x['market'].endswith('_receptions') for x in result['labels'])
    box[0].pop('receptions')
    assert not validate_game(plays, box, schedule)['families']['receptions']['reconciled']


def test_overtime_not_folded_into_regulation_labels():
    plays, box, schedule = fixture()
    plays[-1]['play_type_nfl'] = 'END_QUARTER'
    plays.append({**plays[-1], 'order_sequence': 5, 'play_id': 5, 'qtr': 5,
        'play_type_nfl': 'END_GAME', 'complete_pass': 1, 'receiver_player_id': 'p'})
    box[0]['receptions'] = 1
    result = validate_game(plays, box, schedule)
    assert result['families']['receptions']['reconciled']
    assert all(r['value'] == 0 for r in result['labels'] if r['market'].endswith('_receptions'))


def test_unknown_td_identity_blocks_scorer_labels():
    plays, box, schedule = fixture()
    plays[1]['touchdown'] = 1
    assert not validate_game(plays, box, schedule)['scorer_reconciled']


def test_duplicate_order_and_lateral_fail_closed():
    plays, box, schedule = fixture()
    plays[1]['order_sequence'] = 1
    assert not validate_game(plays, box, schedule)['labels']
    plays, box, schedule = fixture()
    plays[1]['lateral_reception'] = 1
    assert not validate_game(plays, box, schedule)['families']['receiving_yards']['reconciled']
    assert validate_game(plays, box, schedule)['families']['rushing_yards']['reconciled']


def test_held_out_predictions_do_not_see_same_day_outcomes():
    games = [{'date': f'2024-09-{day:02}', 'season': 2024, 'game_id': str(day),
        'labels': [{'player_id': 'p', 'market': '1h_receptions', 'value': 2}]} for day in range(1, 9)]
    games += [{'date': '2025-09-01', 'season': 2025, 'game_id': str(day),
        'labels': [{'player_id': 'p', 'market': '1h_receptions', 'value': 100}]} for day in (20, 21)]
    result = evaluate(games)
    assert len(result['predictions']) == 2
    assert all(r['candidate'] == 2 and r['control'] == 2 for r in result['predictions'])
    assert not result['serving_enabled']


def test_future_changes_cannot_change_prior_prediction():
    games = [{'date': f'2024-09-{day:02}', 'season': 2024, 'game_id': str(day),
        'labels': [{'player_id': 'p', 'market': 'first_td_scorer', 'value': 0}]} for day in range(1, 9)]
    games.append({'date': '2025-09-01', 'season': 2025, 'game_id': '20',
        'labels': [{'player_id': 'p', 'market': 'first_td_scorer', 'value': 1}]})
    original = evaluate(games)['predictions'][0]
    future = deepcopy(games[-1]); future['date'] = '2025-10-01'; future['game_id'] = '21'
    assert evaluate(games + [future])['predictions'][0] == original


def test_settlement_rules_do_not_cross_products():
    from src.services.period_research_status import settlement_lookup
    standard = settlement_lookup('bovada', 'standard_sportsbook', 'nfl')
    builder = settlement_lookup('bovada', 'prop_builder', 'nfl')
    assert standard['rule']['participation'] != builder['rule']['participation']
    assert not standard['ready'] and not builder['ready']
    assert not settlement_lookup('bovada', None, 'nfl')['ready']
