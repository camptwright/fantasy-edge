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


def test_trade_market_values_come_from_the_daily_archive(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from src.api.routers import workspace
    from src.services import fantasy_market
    league = SimpleNamespace(platform="sleeper", settings={"type": 0}, scoring_settings={"rec": 0.5},
                             roster_positions=["QB", "RB", "WR", "FLEX", "BN"])
    params = fantasy_market.cohort(league, 12)
    snap = tmp_path / fantasy_market.key(params) / "snapshots"
    snap.mkdir(parents=True)
    (snap / "20261012T000000.json").write_text(json.dumps({
        "captured_at": datetime.now(timezone.utc).isoformat(), "format": params, "sha256": "x",
        "rows": [{"sleeper_id": "a1", "value": 4200}, {"sleeper_id": "b1", "value": 5100}]}))
    monkeypatch.setattr(fantasy_market, "root", lambda: tmp_path)
    result = workspace.TradeResult(status="withheld", generated_at=datetime.now(timezone.utc),
                                   expires_at=datetime.now(timezone.utc), outlook=workspace.TradeOutlook(status="research"))
    request = workspace.TradeRequest(generated_at=datetime.now(timezone.utc), side_a=["a1"], side_b=["b1", "zz"])
    out = workspace.with_market(result, {"rosters": [{}] * 12}, league, request).outlook.market
    assert (out.status, out.values, out.side_a_total, out.side_b_total) == ("observed", {"a1": 4200, "b1": 5100, "zz": None}, 4200, None)


def finder_data():
    # Mine: two QBs, weak WR. Theirs: two WRs, weak QB. Swapping QB2 for WR2 helps both.
    mine = [p("qb1", "QB", {6: 22, 7: 22}, True), p("qb2", "QB", {6: 18, 7: 18}, True), p("wr1", "WR", {6: 4, 7: 4}, True)]
    theirs = [p("tqb", "QB", {6: 8, 7: 8}, True), p("twr1", "WR", {6: 15, 7: 15}, True), p("twr2", "WR", {6: 12, 7: 12}, True)]
    for x in theirs:
        x["roster_ids"] = [2]
    return {"players": mine + theirs, "roster_positions": ["QB", "WR", "BN", "BN"],
            "rosters": [{"roster_id": 1, "is_mine": True, "name": "Mine", "player_ids": ["qb1", "qb2", "wr1"]},
                        {"roster_id": 2, "is_mine": False, "name": "Them", "player_ids": ["tqb", "twr1", "twr2"]}]}


def test_trade_finder_returns_only_trades_that_help_both_lineups():
    from src.services import trade_finder
    out = trade_finder.find(finder_data())
    assert out["status"] == "research"
    top = out["rows"][0]
    assert (top["give_id"], top["get_id"]) == ("qb2", "twr2")  # spare QB for their spare WR
    assert top["my_gain"] == 16.0 and top["their_gain"] == 20.0  # (12-4)*2 and (18-8)*2
    assert all(r["my_gain"] > 0 and r["their_gain"] > 0 for r in out["rows"])
    assert not any(r["give_id"] == "qb1" and r["get_id"] == "tqb" for r in out["rows"])  # one-sided: excluded


def test_trade_finder_needs_an_owner_roster():
    from src.services import trade_finder
    data = finder_data()
    data["rosters"][0]["is_mine"] = False
    assert trade_finder.find(data)["status"] == "owner_roster_unresolved"
