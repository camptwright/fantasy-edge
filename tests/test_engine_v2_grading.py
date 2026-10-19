import asyncio
import json

from src.services import projection_engine_prospective as P
from src.services import sleeper_season_projections as S


def row(week, position, sleeper, engine, actual, player="p"):
    return {"league_id": "L", "season": 2026, "week": week, "position": position, "game_id": f"g{week}",
            "player_id": f"{player}{week}", "actual": actual, "sleeper": sleeper, "engine": engine,
            "sleeper_error": abs(sleeper - actual), "engine_error": abs(engine - actual)}


def test_blend_rows_match_the_decision_rule():
    out = P.blend_rows([row(6, "WR", 10.0, 14.0, 13.0), row(6, "WR", 0.0, 9.0, 0.0)])
    assert [r["engine"] for r in out] == [12.0, 0.0]
    assert out[0]["engine_error"] == 1.0 and out[0]["sleeper_error"] == 3.0


def test_fit_weights_picks_the_better_source_per_position():
    rows = [row(w, "QB", 10.0, 20.0, 20.0) for w in (6, 7)] + [row(w, "WR", 10.0, 20.0, 10.0) for w in (6, 7)]
    assert P.fit_weights(rows) == {"QB": 1.0, "WR": 0.0}


def test_position_weights_are_scored_out_of_sample():
    assert P.position_weight_candidate([row(6, "QB", 10, 20, 20)])["status"] == "needs_3_graded_weeks_has_1"
    rows = [row(w, "QB", 10.0, 20.0, 20.0) for w in (6, 7, 8)]
    out = P.position_weight_candidate(rows)
    # Each held-out week uses weights from the other two (all 1.0): error 0 vs the half blend's 5.
    assert out["vs_fixed_half"]["paired_difference"] == -5.0 and out["serving_promoted"] is False


def test_season_capture_writes_only_when_sleeper_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_settings", lambda: type("S", (), {"raw_archive_dir": str(tmp_path)})())
    rows = [{"player_id": "4984", "team": "BUF", "player": {"position": "QB"}, "company": "rotowire",
             "week_shard": "_5", "last_modified": 100, "stats": {"pass_yd": 3650.0, "adp_ppr": 21.3}}]

    async def fetcher(season):
        return rows
    first = asyncio.run(S.capture(season=2026, fetcher=fetcher))
    again = asyncio.run(S.capture(season=2026, fetcher=fetcher))
    assert (first["status"], again["status"]) == ("captured", "unchanged")
    saved = json.loads((tmp_path / S.DIRECTORY / "2026_100.json").read_text())
    assert saved["rows"][0]["stats"] == {"pass_yd": 3650.0} and saved["rows"][0]["position"] == "QB"
