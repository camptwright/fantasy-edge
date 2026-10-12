"""Trade outlook: rest-of-season lineup deltas by position for both sides."""

from src.services.trade_outlook import outlook, side_outlook
from tests.test_waiver_guidance import p

SLOTS = ["QB", "RB", "WR", "FLEX", "BN", "BN"]


def test_position_deltas_follow_the_starting_players_position():
    roster = [p("qb", "QB", {6: 20, 7: 20}, True), p("rb1", "RB", {6: 12, 7: 12}, True),
              p("rb2", "RB", {6: 10, 7: 10}, True), p("wr1", "WR", {6: 8, 7: 8}, True)]
    give, receive = [roster[2]], [p("wr_in", "WR", {6: 15, 7: 15}, False)]
    out = side_outlook(roster, give, receive, SLOTS)
    # Before: RB 12+10(flex) WR 8. After: RB 12, WR 15 + 8(flex). Per week: RB -10, WR +15.
    assert out["by_position"] == {"QB": 0.0, "RB": -20.0, "TE": 0.0, "WR": 30.0}
    assert out["lineup_gain"] == 10.0 and [w["gain"] for w in out["weekly"]] == [5.0, 5.0]
    assert out["unmodeled_player_ids"] == []


def test_a_received_player_on_bye_counts_zero_that_week():
    roster = [p("qb", "QB", {6: 20, 7: 20}, True), p("rb1", "RB", {6: 12, 7: 12}, True),
              p("wr1", "WR", {6: 9, 7: 9}, True), p("wr2", "WR", {6: 6, 7: 6}, True)]
    out = side_outlook(roster, [roster[3]], [p("wr_in", "WR", {6: 14}, False)], SLOTS)
    assert [w["gain"] for w in out["weekly"]] == [8.0, -6.0]


def test_outlook_needs_two_distinct_known_rosters():
    players = [p("a1", "WR", {6: 10}, True), p("b1", "WR", {6: 12}, True), p("qb", "QB", {6: 20}, True)]
    data = {"players": players, "roster_positions": SLOTS,
            "rosters": [{"roster_id": 1, "name": "Mine", "player_ids": ["a1", "qb"]}, {"roster_id": 2, "name": "Them", "player_ids": ["b1"]}]}
    out = outlook(data, ["a1"], ["b1"])
    assert out["status"] == "research" and out["side_a"]["team"] == "Mine"
    assert out["side_a"]["lineup_gain"] == 2.0 and out["side_b"]["lineup_gain"] == -2.0
    assert out["player_ros_points"] == {"a1": 10, "b1": 12}
    assert outlook(data, ["a1"], ["qb"])["status"] == "rosters_unresolved"
