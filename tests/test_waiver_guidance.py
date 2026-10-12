"""Waiver guidance values lineup points, not raw bench points."""

from src.services.waiver_guidance import guidance


def p(pid, pos, weeks, rostered, weekly=None):
    return {"player_id": pid, "name": pid, "position": pos, "roster_ids": [1] if rostered else [], "weekly_points": weekly,
            "engine": {"status": "research", "ros_points": sum(weeks.values()),
                       "weeks": [{"week": w, "points": v, "environment": "market_line"} for w, v in weeks.items()]}
            if weeks else {"status": "position_not_modeled"}}


def run(players, slots=("QB", "WR", "FLEX", "K", "BN", "BN")):
    mine = [x["player_id"] for x in players if x["roster_ids"]]
    return guidance(players, mine, set(mine), list(slots))


def test_a_backup_qb_with_big_raw_points_has_no_lineup_value():
    players = [p("qb", "QB", {6: 20, 7: 20}, True), p("wr", "WR", {6: 10, 7: 10}, True), p("rb", "RB", {6: 6, 7: 6}, True),
               p("bench", "WR", {6: 2, 7: 2}, True), p("fa_qb", "QB", {6: 18, 7: 18}, False),
               p("fa_rb", "RB", {6: 9, 7: 9}, False)]
    rows = {r["add_id"]: r for r in run(players)["rows"]}
    assert "fa_qb" not in rows
    assert rows["fa_rb"]["drop_id"] == "bench" and rows["fa_rb"]["lineup_gain"] == 6.0  # 9 replaces 6 in FLEX, twice


def test_byes_count_as_zero_and_the_required_kicker_is_never_dropped():
    players = [p("qb", "QB", {6: 20, 7: 20}, True), p("wr", "WR", {6: 10}, True),  # wr on bye week 7
               p("rb", "RB", {6: 6, 7: 6}, True), p("k", "K", {}, True, weekly=7.0),
               p("fa_wr", "WR", {6: 8, 7: 8}, False), p("fa_k", "K", {}, False, weekly=9.0)]
    rows = {r["add_id"]: r for r in run(players)["rows"]}
    assert rows["fa_wr"]["drop_id"] != "k"
    # Dropping rb gains +2 in each week; dropping the wr (bye in week 7) loses 2 in week 6
    # but gains 8 in week 7 (+6 total), so the bye-week receiver is the better drop.
    assert rows["fa_wr"]["drop_id"] == "wr" and rows["fa_wr"]["lineup_gain"] == 6.0
    assert (rows["fa_wr"]["week_gain"], rows["fa_wr"]["weeks_improved"]) == (-2.0, 1)
    assert rows["fa_k"] == {"add_id": "fa_k", "drop_id": "k", "lineup_gain": None, "week": None, "week_gain": 2.0, "stream": True}


def test_no_engine_weeks_is_an_explicit_status():
    assert run([p("qb", "QB", {}, True)])["status"] == "insufficient_engine_research"
