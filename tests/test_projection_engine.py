"""Projection engine v1 and its prospective grading rules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

from src.services import projection_engine_prospective as prospective
from src.services.projection_engine import (
    RATE_PRIORS, PlayerGame, TeamGame, fit_volume, player_shares,
    predict_volume, project_player, score, shrunk_rate, shrunk_share, weights,
)

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_recency_weights_put_the_newest_game_at_full_weight():
    w = weights(5)
    assert w[-1] == 1.0 and all(np.diff(w) > 0)


def test_one_huge_game_does_not_become_the_projected_share():
    assert shrunk_share([0.45], prior=0.15) < 0.30
    assert shrunk_share([], prior=0.15) == 0.15
    # A steady role stays much closer to the player's own share than the prior.
    steady = shrunk_share([0.28] * 12, prior=0.15)
    assert 0.215 < steady < 0.28


def test_rates_on_few_opportunities_regress_to_the_position_rate():
    assert shrunk_rate(2, 3, prior=0.05, pseudo=120) == pytest.approx((2 + 6) / 123)


def test_volume_fit_recovers_a_known_game_script_effect():
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(300):
        recent, implied, spread = rng.uniform(28, 40), rng.uniform(16, 30), rng.uniform(-10, 10)
        rows.append((recent, implied, spread, 5 + 0.7 * recent + 0.2 * implied + 0.5 * spread))
    coef = fit_volume(rows)
    assert coef == pytest.approx([5, 0.7, 0.2, 0.5], abs=1e-6)
    # Trailing (positive spread) teams throw more.
    assert predict_volume(coef, 34, 22, 7) > predict_volume(coef, 34, 22, -7)


def test_too_little_history_falls_back_to_recent_volume():
    assert fit_volume([(30, 20, 0, 31)] * 10) is None
    assert predict_volume(None, 33.5, 20, 3) == 33.5


def test_player_projection_scales_with_team_volume_and_td_environment():
    team, game = uuid.uuid4(), uuid.uuid4()
    teams = {(game, team): TeamGame(game, team, T0, pass_attempts=35, carries=25, targets=33)}
    games = [PlayerGame(uuid.uuid4(), game, team, T0,
                        {"targets": 9, "receptions": 6, "receiving_yards": 80, "receiving_touchdowns": 1})]
    priors = {"WR": dict.fromkeys(RATE_PRIORS, 0.0)}
    priors["WR"].update(catch_rate=0.62, yards_per_target=8.0, rec_td_rate=0.05)
    share_priors = {"WR": {"targets": 0.15, "rushing_attempts": 0.0, "passing_attempts": 0.0}}
    shares = player_shares("WR", games, teams, share_priors)
    base = project_player("WR", games, priors, shares, 35, 25, 1.0, 0.95)
    more = project_player("WR", games, priors, shares, 42, 25, 1.0, 0.95)
    hotter = project_player("WR", games, priors, shares, 35, 25, 1.2, 0.95)
    assert more["targets"] == pytest.approx(base["targets"] * 42 / 35)
    assert hotter["receiving_touchdowns"] == pytest.approx(base["receiving_touchdowns"] * 1.2)
    assert base["passing_attempts"] == 0.0  # only QBs are given pass volume


def test_score_applies_league_weights_by_internal_stat_name():
    assert score({"receptions": 5, "receiving_yards": 70}, {"receptions": 0.5, "receiving_yards": 0.1}) == 9.5


def test_provider_scoring_hash_matches_the_frozen_provider_formula():
    import hashlib
    import json
    scoring = {"rec": 0.5, "pass_td": 4}
    assert prospective.provider_scoring_hash(scoring) == hashlib.sha256(
        json.dumps(scoring, sort_keys=True).encode()).hexdigest()


def _rows(weeks, engine_error, sleeper_error, positions=("WR",)):
    return [{"league_id": "L", "week": w, "position": p, "actual": 10.0, "sleeper": 12.0,
             "engine": 11.0, "engine_error": engine_error, "sleeper_error": sleeper_error}
            for w in weeks for p in positions for _ in range(3)]


def test_promotion_needs_enough_independent_weeks_even_when_better():
    check = prospective.promotion_check(_rows(range(1, 4), 4.0, 5.0))
    assert not check["eligible_for_owner_review"]
    assert "needs_6_graded_weeks_has_3" in check["blockers"]
    assert check["serving_promoted"] is False


def test_promotion_requires_an_interval_below_zero():
    assert prospective.promotion_check(_rows(range(1, 8), 4.0, 5.0))["eligible_for_owner_review"]
    worse = prospective.promotion_check(_rows(range(1, 8), 5.0, 4.0))
    assert "pool_improvement_not_established" in worse["blockers"]


def test_capture_is_create_only_and_versioned(tmp_path, monkeypatch):
    monkeypatch.setattr(prospective, "archive_root", lambda: tmp_path)
    v = prospective.version()
    assert len(v) == 64 and v == prospective.version()
    path = tmp_path / "forecasts" / "x.json"
    assert prospective.publish(path, {"a": 1}) is True
    assert prospective.publish(path, {"a": 2}) is False  # first observation wins
    assert path.read_text() == '{"a": 1}'
