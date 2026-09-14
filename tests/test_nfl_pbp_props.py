from src.ingest.nfl_pbp_props import longest_rows


def test_longest_rows_uses_only_valid_individual_completed_or_rushing_plays():
    rows = longest_rows([
        {'game_id': 'g', 'complete_pass': 1, 'receiver_player_id': 'r', 'yards_gained': 12},
        {'game_id': 'g', 'complete_pass': '1', 'receiver_player_id': 'r', 'yards_gained': 31},
        {'game_id': 'g', 'complete_pass': 0, 'receiver_player_id': 'r', 'yards_gained': 99},
        {'game_id': 'g', 'rush_attempt': 1, 'rusher_player_id': 'u', 'yards_gained': -2},
        {'game_id': 'g', 'rush_attempt': 1, 'rusher_player_id': 'u', 'yards_gained': 18},
        {'game_id': 'g', 'rush_attempt': 1, 'yards_gained': 40},
        {'game_id': 'g', 'complete_pass': 1, 'receiver_player_id': 'r', 'yards_gained': 'nan'},
        {'game_id': '', 'rush_attempt': 1, 'rusher_player_id': 'u', 'yards_gained': 50},
    ])
    assert rows == {('g', 'r', 'longest_reception'): 31., ('g', 'u', 'longest_rush'): 18.}


def test_longest_rows_keeps_games_and_players_separate():
    rows = longest_rows([
        {'game_id': 'g1', 'complete_pass': 1, 'receiver_player_id': 'r', 'yards_gained': 10},
        {'game_id': 'g2', 'complete_pass': 1, 'receiver_player_id': 'r', 'yards_gained': 20},
        {'game_id': 'g1', 'complete_pass': 1, 'receiver_player_id': 'other', 'yards_gained': 30},
    ])
    assert rows == {('g1', 'r', 'longest_reception'): 10.,
                    ('g2', 'r', 'longest_reception'): 20.,
                    ('g1', 'other', 'longest_reception'): 30.}
