"""Correlated outcome simulation, the gated blend, and lineup research."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.services import fantasy_outcomes as fo

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
MODEL = fo.load_model()


def test_committed_model_is_fitted_gated_and_never_promoted():
    assert MODEL and MODEL["serving_promoted"] is False
    assert MODEL["correlations"]["same:QB-WR"]["rho"] > 0.2
    if MODEL["blend_status"].startswith("provider_only"):
        assert set(MODEL["blend_weights"].values()) == {0.0}


def test_blend_needs_a_provider_and_otherwise_weights_the_engine():
    model = {"blend_weights": {"WR": 0.25}}
    assert fo.blend_mean("WR", None, 12.0, model) == (None, "missing_provider_projection")
    assert fo.blend_mean("WR", 10.0, None, model) == (10.0, "provider")
    assert fo.blend_mean("WR", 10.0, 14.0, model) == (pytest.approx(11.0), "blend")


def test_same_team_stack_is_correlated_and_final_points_are_fixed():
    players = [{"player_id": "qb", "position": "QB", "team": "A", "opponent": "B", "mean": 20},
               {"player_id": "wr", "position": "WR", "team": "A", "opponent": "B", "mean": 14},
               {"player_id": "rb", "position": "RB", "team": "C", "opponent": "D", "mean": 12},
               {"player_id": "done", "position": "TE", "team": "E", "final_points": 7.5}]
    s = fo.simulate(players, MODEL, draws=20000)
    assert np.corrcoef(s["qb"], s["wr"])[0, 1] > 0.2
    assert abs(np.corrcoef(s["qb"], s["rb"])[0, 1]) < 0.05
    assert set(s["done"]) == {7.5}
    independent = fo.simulate(players, MODEL, draws=20000, correlated=False)
    assert abs(np.corrcoef(independent["qb"], independent["wr"])[0, 1]) < 0.05


def test_dispersion_grows_with_projection_and_intervals_are_ordered():
    low, *_ = fo.spread("WR", 4.0, MODEL)
    high, probs, values = fo.spread("WR", 18.0, MODEL)
    assert high > low and list(values) == sorted(values)


def player(pid, pos, team, opp, *, points=10.0, kickoff=NOW + timedelta(hours=2), status="scheduled",
           locked=False, injury=None):
    return {"player_id": pid, "name": pid, "position": pos, "nfl_team_id": team, "nfl_opponent_id": opp,
            "week_game_status": status, "week_kickoff": kickoff.isoformat() if kickoff else None,
            "locked": locked, "injury_status": injury, "weekly_points": points,
            "weekly_evidence": {"status": "pregame_provider_projection"}, "engine": {}}


def league():
    slots = ["QB", "WR", "FLEX"]
    by_id = {p["player_id"]: p for p in [
        player("q1", "QB", "A", "B", points=18), player("w1", "WR", "A", "B", points=12),
        player("r1", "RB", "C", "D", points=6), player("bench", "RB", "E", "F", points=15),
        player("q2", "QB", "B", "A", points=18), player("w2", "WR", "B", "A", points=12),
        player("r2", "RB", "D", "C", points=12)]}
    return by_id, slots


def test_research_reports_win_probability_and_a_better_lineup():
    by_id, slots = league()
    out = fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], ["q1", "w1", "r1", "bench"], slots, {}, NOW, draws=4000)
    assert out["status"] == "estimated_research" and out["serving_promoted"] is False
    assert 0 < out["current"]["win_probability"] < 0.5
    best = out["max_win_probability_lineup"]
    assert "bench" in best["player_ids"] and best["win_probability"] > out["current"]["win_probability"]
    assert best["changes"] == [{"slot": "FLEX", "start": "bench", "replaces": "r1"}]
    assert out["player_ranges"]["q1"]["p10"] < out["player_ranges"]["q1"]["p90"]


def test_lineup_changes_ignore_starters_that_only_swap_slots():
    slots = ["QB", "RB", "FLEX", "TE"]
    current = ["q1", "rb_a", "rb_b", "te1"]
    # rb_a and rb_b trade RB/FLEX and te2 replaces te1: one real change.
    assert fo.lineup_changes(slots, current, ["q1", "rb_b", "rb_a", "te2"]) == [
        {"slot": "TE", "start": "te2", "replaces": "te1"}]
    # A bench back takes RB while the old RB slides to FLEX: it replaces the
    # starter who actually leaves, not the one who moved.
    assert fo.lineup_changes(slots, current, ["q1", "bench", "rb_a", "te1"]) == [
        {"slot": "RB", "start": "bench", "replaces": "rb_b"}]
    assert fo.lineup_changes(slots, current, ["q1", "rb_b", "rb_a", "te1"]) == []


def test_in_progress_games_withhold_and_finished_games_use_recorded_points():
    by_id, slots = league()
    by_id["r2"] = player("r2", "RB", "D", "C", kickoff=NOW - timedelta(hours=1), locked=True)
    out = fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], ["q1", "w1", "r1"], slots, {}, NOW)
    assert out["status"] == "withheld" and out["blockers"][0]["reason"] == "game_in_progress"
    by_id["r2"] = player("r2", "RB", "D", "C", kickoff=NOW - timedelta(hours=4), status="final", locked=True)
    assert fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], [], slots, {}, NOW)["blockers"][0]["reason"] == "final_without_recorded_points"
    out = fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], [], slots, {"r2": 31.0}, NOW, draws=2000)
    assert out["player_ranges"]["r2"] == {**out["player_ranges"]["r2"], "p10": 31.0, "p90": 31.0, "basis": "final_recorded"}


def test_bye_and_out_starters_score_zero_but_stay_replaceable():
    by_id, slots = league()
    by_id["r1"] = {**player("r1", "RB", "C", None, kickoff=None, locked=True), "week_game_status": "no_game_this_week"}
    out = fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], ["q1", "w1", "r1", "bench"], slots, {}, NOW, draws=2000)
    assert out["player_ranges"]["r1"]["basis"] == "bye"
    assert "bench" in out["max_win_probability_lineup"]["player_ids"]
    by_id["r1"] = player("r1", "RB", "C", "D", injury="Out")
    assert fo.research(by_id, ["q1", "w1", "r1"], ["q2", "w2", "r2"], [], slots, {}, NOW, draws=2000)["player_ranges"]["r1"]["basis"] == "designated_out"


def test_provider_reserve_aliases_and_conflicting_event_holds():
    p = player('r', 'RB', 'C', 'D', injury='INJURY_RESERVE')
    entry, reason = fo._entry(p, {}, NOW)
    assert reason is None and entry['basis'] == 'designated_out' and entry['final_points'] == 0
    entry, reason = fo._entry({**p, 'game_availability': {'hold_recommendation': True}}, {}, NOW)
    assert entry is None and reason == 'event_availability_hold'
    # Final platform scores are actual evidence, even if stale platform labels remain IR.
    final = {**p, 'week_game_status': 'final', 'game_availability': {'hold_recommendation': True}}
    entry, reason = fo._entry(final, {'r': 12}, NOW)
    assert reason is None and entry['final_points'] == 12
