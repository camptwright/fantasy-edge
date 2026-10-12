"""Prospective win-probability capture and grading (research only)."""

from datetime import datetime, timedelta, timezone

from src.models.facts import Game
from src.models.sleeper import SleeperLeagueSnapshot
from src.services import outcome_prospective as op

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def checkpoint(p=0.62, status="estimated_research", final=0):
    return {"league_id": "L", "week": 6, "outcome_simulation": {
        "status": status, "known_final_starters": final, "model": {"fitted_at": "2026-10-12"},
        "current": {"win_probability": p, "mean": 110.0, "opponent_mean": 104.0}},
        "matchup_rosters": {"mine": {"roster_id": 3}, "opponent": {"roster_id": 7}}}


def test_only_fully_pregame_estimates_are_forecasts():
    row = op.forecast(checkpoint(), NOW)
    assert (row["season"], row["week"], row["roster_id"], row["opponent_roster_id"], row["win_probability"]) == (2026, 6, 3, 7, 0.62)
    assert op.forecast(checkpoint(final=1), NOW) is None  # a starter's game already finished
    assert op.forecast(checkpoint(status="withheld"), NOW) is None
    assert op.forecast(checkpoint(p=float("nan")), NOW) is None


def test_score_reports_brier_against_a_coin_flip():
    rows = [{"season": 2026, "week": 6, "win_probability": 0.8, "won": 1}, {"season": 2026, "week": 6, "win_probability": 0.3, "won": 1}]
    s = op.score(rows)
    assert s["n"] == 2 and s["brier"] == round((0.04 + 0.49) / 2, 4) and s["coin_flip_brier"] == 0.25
    assert op.score([])["brier"] is None


async def test_latest_pregame_capture_is_graded_only_after_the_week_settles(db, tmp_path):
    kickoff = NOW - timedelta(days=2)
    db.add(Game(sport="nfl", season=2026, week=6, game_type="REG", status="final", game_time=kickoff))
    db.add(SleeperLeagueSnapshot(league_id="L", week=6, kind="matchups", synced_at=NOW - timedelta(hours=1),
                                 payload=[{"roster_id": 3, "points": 120.5}, {"roster_id": 7, "points": 99.0}]))
    await db.commit()
    for at, p in ((kickoff - timedelta(hours=8), 0.4), (kickoff - timedelta(hours=1), 0.7)):
        row = op.forecast(checkpoint(p), at)
        op.publish(tmp_path / "forecasts" / f"L-{at.timestamp()}.json", row)
    early = await op.report(db, now=kickoff + timedelta(hours=5), root=tmp_path)
    assert early["statuses"] == {"awaiting_final_week": 1} and early["summary"]["n"] == 0
    out = await op.report(db, now=NOW, root=tmp_path)
    assert out["statuses"] == {"graded": 1} and out["captured_matchups"] == 1 and out["serving_promoted"] is False
    assert out["summary"]["brier"] == round((0.7 - 1) ** 2, 4)  # the latest pregame capture (0.7), not 0.4
