from src.services.nfl_predictors import (
    build_player_profiles,
    build_team_profiles,
    predict_matchup,
    predict_player_stat,
)


def _team_rows(team, points_for, points_against):
    return [{"team": team, "points_for": points_for, "points_against": points_against, "pass_epa": 1.0, "rush_epa": 0.5} for _ in range(4)]


def test_matchup_requires_minimum_sample_and_produces_transparent_prediction():
    profiles = build_team_profiles(_team_rows("KC", 28, 20) + _team_rows("BAL", 21, 24))
    result = predict_matchup(profiles["KC"], profiles["BAL"])
    assert result.qualified is True
    assert result.expected_home_points is not None
    assert 0 < result.home_win_probability < 1


def test_player_prediction_is_gated_when_stat_sample_is_insufficient():
    profiles = build_player_profiles([{"player_name": "A Player", "passing_yards": 250}] * 2)
    assert "A Player" not in profiles


def test_player_projection_returns_range_from_complete_rows():
    rows = [{"player_name": "A Player", "team": "KC", "rushing_yards": n} for n in (80, 90, 70, 100)]
    profile = build_player_profiles(rows)["A Player"]
    prediction = predict_player_stat(profile, "rushing_yards")
    assert prediction.qualified is True
    assert prediction.floor <= prediction.projection <= prediction.ceiling
