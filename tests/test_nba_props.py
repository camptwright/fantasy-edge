from datetime import datetime, timedelta, timezone

from src.ingest.nba_players import roster
from src.ingest.pinnacle_props import parse
from src.services import nba_prop_engine as E
from src.services.nba_context import athletes, market


def test_roster_reads_espn_athletes_and_skips_bad_ids():
    payload = {"athletes": [{"id": "4278039", "fullName": "Nickeil Alexander-Walker", "position": {"abbreviation": "G"}},
                            {"id": "x", "fullName": "Bad Id"}, {"id": "5", "fullName": ""}]}
    assert roster(payload) == [("4278039", "Nickeil Alexander-Walker", "G")]


def test_pinnacle_specials_become_two_way_props():
    parent = {"participants": [{"alignment": "home", "name": "Miami Heat"}, {"alignment": "away", "name": "Minnesota Timberwolves"}],
              "startTime": "2026-10-21T23:30:00Z"}
    matchups = [{"id": 1, "parent": parent, "special": {"category": "Player Props", "description": "Bam Adebayo Total Assists"},
                 "participants": [{"id": 11, "name": "Over"}, {"id": 12, "name": "Under"}]},
                {"id": 2, "parent": parent, "special": {"category": "Player Props", "description": "Bam Adebayo Total Dunks"},
                 "participants": [{"id": 21, "name": "Over"}, {"id": 22, "name": "Under"}]},
                {"id": 3, "special": {"category": "Futures", "description": "Heat Total Wins"}}]
    markets = [{"matchupId": 1, "type": "total", "period": 0, "status": "open",
                "prices": [{"participantId": 11, "points": 3.5, "price": -122}, {"participantId": 12, "points": 3.5, "price": -108}]},
               {"matchupId": 2, "type": "total", "period": 0, "prices": [{"participantId": 21, "points": 1.5, "price": -110}]}]
    rows = parse(matchups, markets, "nba")
    assert rows == [{"name": "Bam Adebayo", "stat": "assists", "home": "Miami Heat", "away": "Minnesota Timberwolves",
                     "kickoff": datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc), "line": 3.5, "over": -122, "under": -108}]


def test_espn_summary_gives_starters_total_and_home_spread():
    box = {"boxscore": {"teams": [{"homeAway": "home", "team": {"abbreviation": "SA"}}, {"homeAway": "away", "team": {"abbreviation": "OKC"}}],
                        "players": [{"team": {"id": "24"}, "statistics": [{"athletes": [
                            {"athlete": {"id": "1"}, "starter": True, "didNotPlay": False},
                            {"athlete": {"id": "2"}, "starter": False, "didNotPlay": True}]}]}]},
           "pickcenter": [{"overUnder": 210.5, "details": "OKC -9.5"}]}
    assert athletes(box) == {"1": ("24", True)}
    assert market(box) == (210.5, 9.5)  # away favourite: home +9.5
    box["pickcenter"] = [{"overUnder": 220.0, "details": "SA -3"}]
    assert market(box) == (220.0, -3.0)
    box["pickcenter"] = []
    assert market(box) == (None, None)


def played(i, minutes, points, season=2027):
    t = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=i)
    return E.Played(str(i), t, season, "a", "b", True, {"minutes": minutes, "points": points, **{s: 1.0 for s in E.BASE if s != "points"}})


def test_base_projection_weights_recent_games_and_shrinks_to_position():
    league = E.League()
    league.add("G", "b", "g0", {"minutes": 1000.0, "points": 500.0, **{s: 100.0 for s in E.BASE if s != "points"}})
    prior = [played(i, 30.0, 30.0) for i in range(5)]
    out = E.base_projection(prior, "G", league, 2027, half_life=10, shrink=60)
    # 30 min at 1.0 pts/min shrunk toward 0.5/min with 60 prior minutes.
    assert abs(out["minutes"] - 30.0) < 1e-9 and 0.5 * 30 < out["points"] < 30.0
    assert E.base_projection([played(0, 0.0, 0.0)], "G", league, 2027) is None  # no minutes played


def test_opponent_factor_is_shrunk_and_relative_to_league():
    league = E.League()
    for g in range(4):
        league.add("G", "soft", f"s{g}", {"minutes": 48.0, "points": 30.0})
        league.add("G", "hard", f"h{g}", {"minutes": 48.0, "points": 10.0})
    soft, hard = league.opponent_factor("soft", "G", "points"), league.opponent_factor("hard", "G", "points")
    assert 1.0 < soft < 1.5 and 0.5 < hard < 1.0
    assert league.opponent_factor("unknown", "G", "points") == 1.0


def test_over_probability_reads_tercile_quantiles():
    artifact = {"distribution": {"points": {"edges": [5.0, 15.0], "quantiles": [[0.0, 1.0, 2.0]] * 3}}}
    assert E.over_probability("points", 10.0, 10.0, artifact) == 0.5
    assert E.over_probability("points", 10.0, 25.0, artifact) == 0.0
    assert E.over_probability("points", None, 10.0, artifact) is None


def test_freeze_writes_each_game_once_inside_the_window(tmp_path):
    from src.services.prop_board import freeze
    now = datetime(2026, 10, 20, 22, 0, tzinfo=timezone.utc)
    row = {"game_id": "g", "game_time": "2026-10-20T23:00:00+00:00", "player_id": "p", "player": "P", "team": "NY", "opponent": "PHI",
           "stat": "points", "line": 20.5, "books": 1, "fair_over": 0.5, "best_over": None, "best_under": None,
           "engine": {"projection": 21.0, "over_probability": 0.52}}
    later = {**row, "game_id": "h", "game_time": "2026-10-21T02:00:00+00:00"}
    assert freeze({"rows": [row, later]}, now, tmp_path) == 1
    assert freeze({"rows": [{**row, "line": 21.5}]}, now, tmp_path) == 0  # first record is kept
    assert (tmp_path / "nba-prop-forecasts" / "g.json").exists() and not (tmp_path / "nba-prop-forecasts" / "h.json").exists()
