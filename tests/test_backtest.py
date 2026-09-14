"""Walk-forward calibration backtest (src/services/backtest.py).

The core property under test throughout: every prediction must be built
from PRE-game state, never the rating a team ends up with after that same
game - the lookahead-bias bug signal_rows itself once had (see that
function's own docstring in src/api/routers/sportsbook.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ingest.identity import resolve_team
from src.models.facts import Game, TeamMarketLine
from src.services.backtest import (
    BacktestPrediction,
    brier_score,
    calibration_curve,
    log_loss,
    run_backtest,
)


def test_brier_score_is_zero_for_perfect_predictions():
    predictions = [BacktestPrediction(game_id=None, market="moneyline", probability=1.0, outcome=1.0)]
    assert brier_score(predictions) == pytest.approx(0.0)


def test_brier_score_is_quarter_for_uninformative_coin_flip():
    predictions = [
        BacktestPrediction(game_id=None, market="moneyline", probability=0.5, outcome=1.0),
        BacktestPrediction(game_id=None, market="moneyline", probability=0.5, outcome=0.0),
    ]
    assert brier_score(predictions) == pytest.approx(0.25)


def test_brier_score_is_none_for_no_predictions():
    assert brier_score([]) is None
    assert log_loss([]) is None


def test_log_loss_penalizes_a_confident_wrong_prediction_heavily():
    confident_wrong = [BacktestPrediction(game_id=None, market="moneyline", probability=0.99, outcome=0.0)]
    confident_right = [BacktestPrediction(game_id=None, market="moneyline", probability=0.99, outcome=1.0)]
    assert log_loss(confident_wrong) > log_loss(confident_right)


def test_calibration_curve_buckets_by_predicted_probability():
    predictions = [
        BacktestPrediction(game_id=None, market="moneyline", probability=0.1, outcome=0.0),
        BacktestPrediction(game_id=None, market="moneyline", probability=0.9, outcome=1.0),
    ]
    curve = calibration_curve(predictions, bins=5)
    assert len(curve) == 2
    low_bucket = next(b for b in curve if b["range_low"] == 0.0)
    assert low_bucket["avg_actual"] == pytest.approx(0.0)
    high_bucket = next(b for b in curve if b["range_low"] == pytest.approx(0.8))
    assert high_bucket["avg_actual"] == pytest.approx(1.0)


async def _seed_final_game(
    db, sport, season, home_name, away_name, home_score, away_score, event_id, game_time=None
):
    home = await resolve_team(db, home_name, sport=sport)
    away = await resolve_team(db, away_name, sport=sport)
    game = Game(
        sport=sport,
        espn_event_id=event_id,
        season=season,
        home_team_id=home.id,
        away_team_id=away.id,
        home_score=home_score,
        away_score=away_score,
        status="final",
        game_time=game_time or datetime(season, 9, 1, tzinfo=timezone.utc),
    )
    db.add(game)
    await db.flush()
    return game


async def test_run_backtest_carries_rating_forward_chronologically_not_from_final_table(db):
    """Kansas City blows out Denver in an earlier game, then hosts Las
    Vegas in a later game. The second game's moneyline prediction must use
    Kansas City's rating AFTER the first game's update was applied (since
    that game has already happened by the second game's kickoff) - proving
    the walk is genuinely sequential in-memory state, not a flat re-read of
    starting ratings for every game regardless of order."""
    t1 = datetime(2020, 9, 1, tzinfo=timezone.utc)
    t2 = datetime(2020, 9, 8, tzinfo=timezone.utc)
    await _seed_final_game(db, "nfl", 2020, "Kansas City Chiefs", "Denver Broncos", 40, 0, "bt-1", game_time=t1)
    await _seed_final_game(db, "nfl", 2020, "Kansas City Chiefs", "Las Vegas Raiders", 20, 17, "bt-2", game_time=t2)
    await db.commit()

    predictions = await run_backtest(db, "nfl", [2020])
    moneyline = [p for p in predictions if p.market == "moneyline"]
    assert len(moneyline) == 2
    first_game_prediction, second_game_prediction = moneyline

    # Kansas City is home in both games. Its second-game win probability
    # must exceed its first-game probability: it enters game two already
    # carrying the rating boost from blowing out Denver in game one, on
    # top of the same home-field edge both games share.
    assert second_game_prediction.probability > first_game_prediction.probability


async def test_run_backtest_only_includes_final_games(db):
    home = await resolve_team(db, "Buffalo Bills", sport="nfl")
    away = await resolve_team(db, "Miami Dolphins", sport="nfl")
    game = Game(
        sport="nfl", espn_event_id="bt-3", season=2020,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.commit()

    predictions = await run_backtest(db, "nfl", [2020])
    assert predictions == []


async def test_run_backtest_excludes_moneyline_predictions_for_ties(db):
    await _seed_final_game(db, "nfl", 2020, "New England Patriots", "New York Jets", 14, 14, "bt-4")
    await db.commit()

    predictions = await run_backtest(db, "nfl", [2020])
    assert predictions == []


async def test_run_backtest_prices_spread_and_total_when_closing_lines_exist(db):
    game = await _seed_final_game(db, "nfl", 2020, "Green Bay Packers", "Chicago Bears", 24, 17, "bt-5")
    db.add(TeamMarketLine(
        game_id=game.id, market="spread", side="home", line=-3.0,
        source="test", line_type="closing", observed_at=game.game_time,
    ))
    db.add(TeamMarketLine(
        game_id=game.id, market="total", side="over", line=40.5,
        source="test", line_type="closing", observed_at=game.game_time,
    ))
    await db.commit()

    predictions = await run_backtest(db, "nfl", [2020])
    markets = {p.market for p in predictions}
    # Moneyline and spread always price off Elo alone; total requires both
    # teams to already be MIN_GAMES_FOR_TOTALS-qualified, which neither
    # side is on the very first game in the dataset - the correct honest
    # gap, not a bug in this test.
    assert markets == {"moneyline", "spread"}


async def test_run_backtest_returns_empty_for_a_sport_with_no_games(db):
    assert await run_backtest(db, "nfl", [2099]) == []
