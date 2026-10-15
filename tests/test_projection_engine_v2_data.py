from datetime import datetime, timezone

from src.services import projection_engine_v2_data as D
from src.services.projection_engine_v2_prospective import candidates


def schedule(game_id, week, home="AAA", away="BBB", score="20"):
    return {"game_id": game_id, "season": "2025", "week": str(week), "game_type": "REG", "gameday": f"2025-09-{6 + 7 * week:02d}",
            "gametime": "13:00", "home_team": home, "away_team": away, "spread_line": "3.0", "total_line": "44.0",
            "home_score": score, "away_score": score}


def stat(game_id, player, team, targets, week, position="WR"):
    row = {c: "0" for c in D.STAT_COLUMNS} | {c: "0" for c in D.FUMBLES}
    row.update(game_id=game_id, player_id=player, team=team, position=position, season_type="REG",
               targets=str(targets), receiving_air_yards="", season="2025", week=str(week))
    return row


def roster(player, team, week, status="ACT", position="WR", sleeper="", rookie="", pick=""):
    return {"gsis_id": player, "season": "2025", "week": str(week), "team": team, "status": status, "position": position,
            "game_type": "REG", "pfr_id": "", "sleeper_id": sleeper, "rookie_year": rookie, "draft_number": pick}


def data():
    schedules = [schedule("g1", 1), schedule("g2", 2), schedule("g3", 3, score="")]
    stats = [stat("g1", "a1", "AAA", 6, 1), stat("g1", "a2", "AAA", 4, 1), stat("g1", "b1", "BBB", 9, 1),
             stat("g2", "a2", "AAA", 8, 2), stat("g2", "b2", "BBB", 5, 2)]
    rosters = [roster("a1", "AAA", 3), roster("a2", "AAA", 3), roster("x", "AAA", 3, status="RES"),
               roster("r", "AAA", 3, sleeper="77", rookie="2025", pick="12")]
    sleeper = {(2025, 1): {"77": {"rec_tgt": "4", "gp": 1}}}
    return D.assemble(schedules, stats, [], rosters, [{"sleeper_id": "88.0", "gsis_id": "s"}], sleeper)


def test_assemble_reads_csv_strings_and_keeps_unplayed_games_out_of_history():
    d = data()
    assert d["games"]["g3"]["final"] is False and d["games"]["g1"]["home_spread"] == -3.0
    assert set(d["players"]) == {("g1", "a1"), ("g1", "a2"), ("g1", "b1"), ("g2", "a2"), ("g2", "b2")}
    assert d["teams"][("g1", "AAA")]["targets"] == 10
    assert d["rookie"] == {(2025, "r"): 12}
    assert d["sleeper_to_gsis"]["88"] == "s"  # float-formatted ids normalise
    assert d["sleeper"][(2025, 1)] == {"r": {"rec_tgt": "4", "gp": 1}}


def test_returning_teammates_never_include_the_opponent():
    """Regression: per-game player lists keyed by game alone counted opponents as returning."""
    # a1 played week 1 and missed week 2, so he is returning for AAA in week 3. BBB's b1 also
    # missed week 2; under the bug he counted for AAA too (return_targets 1.6, not 0.6).
    week3 = D.team_availability(data(), {"out": {}, "depth": {}},
                                [(2025, 3, "AAA", datetime(2025, 9, 27, tzinfo=timezone.utc))])[(2025, 3, "AAA")]
    assert week3["*"]["return_targets"] == 6 / 10


def test_listed_out_players_count_as_vacated_not_returning():
    d = data()
    week3 = D.team_availability(d, {"out": {(2025, 3, "AAA"): {"a1"}}, "depth": {}},
                                [(2025, 3, "AAA", datetime(2025, 9, 27, tzinfo=timezone.utc))])[(2025, 3, "AAA")]
    assert week3["*"]["out_targets"] == 6 / 10 and "return_targets" not in week3["*"]


def test_sleeper_context_uses_only_past_games():
    d = data()
    assert D.sleeper_context(d, 2025, 1, "r") == (None, None)  # week 1's own projection never feeds week 1
    s1, prev = D.sleeper_context(d, 2025, 2, "r")
    assert s1 == prev == {"rec_tgt": "4", "gp": 1}


def test_candidates_come_from_the_weekly_roster_and_skip_reserve():
    assert candidates(data(), 2025, 3, "AAA") == [("a1", "WR"), ("a2", "WR"), ("r", "WR")]
    assert candidates(data(), 2025, 2, "AAA") == []
