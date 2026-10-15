from datetime import datetime, timedelta, timezone

import numpy as np

from src.services import projection_engine_v2 as v2

T0 = datetime(2025, 9, 7, 17, tzinfo=timezone.utc)


def game(week, targets, team_targets=30, team="A", season=2025, snap=0.8, carries=0, team_carries=25):
    stats = {s: 0.0 for s in v2.STATS}
    stats.update(targets=targets, receptions=targets * 0.6, receiving_yards=targets * 8.0,
                 rushing_attempts=carries)
    return {"season": season, "week": week, "kickoff": T0 + timedelta(days=7 * week), "team": team,
            "position": "WR", "stats": stats, "team_targets": team_targets, "team_carries": team_carries,
            "team_pass_att": 33, "team_dropbacks": 36, "team_air_yards": 250, "team_rz_targets": 4,
            "team_rz_carries": 3, "team_gl_carries": 1, "snap_pct": snap}


def test_ewma_weights_recent_games_and_skips_missing():
    assert v2.ewma([0.0, 1.0], half_life=1.0) == 2 / 3
    assert v2.ewma([None, 1.0]) == 1.0
    assert np.isnan(v2.ewma([None]))


def test_shrunk_share_moves_toward_prior_with_little_history():
    assert v2.shrunk_share([], 0.1) == 0.1
    one, many = v2.shrunk_share([0.4], 0.1), v2.shrunk_share([0.4] * 10, 0.1)
    assert 0.1 < one < many < 0.4


def rates():
    return v2.league_rates([game(w, 6) for w in range(1, 6)], positions=("WR",))


def test_player_features_use_only_prior_games_and_flag_team_changes():
    prior = [game(w, 3 * w) for w in range(1, 5)]
    target = {**game(5, 0), "team": "B"}
    f = v2.player_features(prior, target, {"rookie_pick": None}, rates())
    assert f["share_last_targets"] == 12 / 30
    assert f["v1_share_targets"] == rates()["WR"]["share_prior"]["targets"]  # no games for team B yet
    assert f["team_changed_d"] == 1.0 / (1 + 4)
    assert f["games_season"] == 4


def test_player_features_read_availability_and_depth_context():
    ctx = {"availability": {"*": {"out_targets": 0.3}, "WR": {"out_targets": 0.2}}, "depth_rank": 1}
    f = v2.player_features([game(1, 5)], game(2, 0), ctx, rates())
    assert f["out_targets"] == 0.3 and f["out_pos_targets"] == 0.2
    assert f["depth_starter"] == 1.0 and f["depth_missing"] == 0.0


def test_ridge_recovers_a_linear_signal_and_handles_missing_values():
    rng = np.random.default_rng(0)
    rows = [{"x": float(x), "z": (float(z) if i % 5 else None)} for i, (x, z) in enumerate(rng.normal(size=(400, 2)))]
    frame = v2.Frame.from_rows(rows, ["x", "z"])
    y = 2 * frame.col("x") + 1
    m = v2.fit_ridge(frame, np.ones(400, bool), y, ["x", "z"], alpha=1e-6)
    assert np.allclose(m.predict(frame), y, atol=1e-3)
    assert m.flags == [1]  # missing indicator for z


def test_fit_and_predict_end_to_end_on_a_toy_league():
    players, teams = [], []
    rng = np.random.default_rng(1)
    for w in range(1, 30):
        for team in ("A", "B"):
            teams.append({"t_pass": 33.0, "t_car": 25.0, "implied": 22.0 + rng.normal(), "spread": 0.0,
                          "pass_att": 33.0 + rng.normal(), "carries": 25.0 + rng.normal()})
        for share in (0.1, 0.25):
            g = game(w, round(30 * share + rng.normal()))
            players.append({**g, "v1_share_targets": share, "t_pass": 33.0, "t_car": 25.0, "implied": 22.0,
                            "spread": 0.0, "t_tpa": 0.9, "r_catch_rate": 0.6, "lg_catch_rate": 0.6,
                            "r_yards_per_target": 8.0, "lg_yards_per_target": 8.0})
    tf = v2.Frame.from_rows(teams, list(v2.TEAM_FEATURES))
    team_y = {k: np.array([t[k] for t in teams]) for k in ("pass_att", "carries")}
    frame = v2.Frame.from_rows(players)
    train = np.arange(len(players)) < len(players) - 2
    model = v2.fit(tf, team_y, np.ones(len(teams), bool), frame, train, ("core",))
    out = v2.predict(model, frame, ~train)
    targets = out[:, v2.STATS.index("targets")]
    assert targets[1] > targets[0] > 0  # the bigger share gets more targets
    yards = out[:, v2.STATS.index("receiving_yards")]
    assert np.allclose(yards / targets, 8.0, rtol=0.1)
