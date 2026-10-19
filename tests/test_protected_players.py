"""IR/taxi players on your roster are never suggested as waiver drops or trade gives."""
from src.api.routers import workspace as ws


def player(pid, pos="QB", **extra):
    return {"player_id": pid, "name": f"P{pid}", "position": pos, "locked": False, "roster_ids": [1], **extra}


def data(**extra):
    base = {"rosters": [{"roster_id": 1, "is_mine": True, "player_ids": ["dart", "a", "b", "s"]},
                        {"roster_id": 2, "is_mine": False, "player_ids": ["x"]}],
            "matchup_rosters": {"mine": {"starters": ["s"]}}, "players": [], "roster_positions": ["QB", "BN", "IR"]}
    return {**base, **extra}


def test_waiver_move_dropping_an_ir_player_swaps_to_an_equal_drop_or_is_withheld():
    add = player("fa", roster_ids=[], replacement_pool_member=True, decision_points=12.0)
    players = [add, player("dart"), player("a"), player("b"), player("s")]
    by_id = {p["player_id"]: p for p in players}
    moves = [{"add_id": "fa", "drop_id": "dart", "lineup_gain": 3.0, "scope": "unstarted_slots_only", "equivalent_drop_ids": ["dart", "a"]},
             {"add_id": "fa", "drop_id": "dart", "lineup_gain": 2.0, "scope": "unstarted_slots_only", "equivalent_drop_ids": []}]
    d = data(waivers={"status": "lock_preserving_candidate", "moves": moves}, _protected={"dart": "IR"})
    _, view = ws.roster_context(d, by_id)
    assert [m.drop.player_id for m in view.moves] == ["a"] and view.excluded_moves == 1
    assert all(e.player_id != "dart" for m in view.moves for e in m.equivalent_drops)


def test_engine_waivers_filter_protected_players_without_get_recalculation(monkeypatch):
    import src.services.waiver_guidance as wg
    def fake(*args, **kwargs):
        raise AssertionError('A GET must not recalculate waiver guidance')
    monkeypatch.setattr(wg, "guidance", fake)
    add = player("fa", roster_ids=[])
    players = [add, player("dart"), player("a"), player("b"), player("s")]
    by_id = {p["player_id"]: p for p in players}
    stored = {"status": "research", "rows": [{"add_id": "fa", "drop_id": "dart", "lineup_gain": 25.0, "week": 7, "week_gain": 3.0,
                                              "weeks_improved": 5, "weeks": 6}]}
    d = data(players=players, waiver_guidance=stored, _protected={"dart": "IR"})
    view = ws.engine_waiver_context(d, by_id)
    assert view.rows == []
    assert [p.player_id for p in view.protected] == ["dart"]


def test_unprotected_rosters_keep_the_background_rows(monkeypatch):
    import src.services.waiver_guidance as wg
    monkeypatch.setattr(wg, "guidance", lambda *a: (_ for _ in ()).throw(AssertionError("no re-solve needed")))
    players = [player("fa", roster_ids=[]), player("dart"), player("a"), player("b"), player("s")]
    stored = {"status": "research", "rows": [{"add_id": "fa", "drop_id": "a", "lineup_gain": 25.0, "week": 7, "week_gain": 3.0,
                                              "weeks_improved": 5, "weeks": 6}]}
    view = ws.engine_waiver_context(data(players=players, waiver_guidance=stored, _protected={"dart": "IR"}), {p["player_id"]: p for p in players})
    assert [r.compare.player_id for r in view.rows] == ["a"]


def test_trade_finder_never_offers_a_protected_player():
    from src.services import trade_finder

    def eng(pts):
        return {"status": "research", "ros_points": pts * 3, "weeks": [{"week": w, "points": pts} for w in (7, 8, 9)]}
    players = [{"player_id": "dart", "position": "QB", "engine": eng(18)}, {"player_id": "wr1", "position": "WR", "engine": eng(8)},
               {"player_id": "qb2", "position": "QB", "engine": eng(14)}, {"player_id": "wr2", "position": "WR", "engine": eng(16)}]
    d = {"players": players, "roster_positions": ["QB", "WR", "BN"],
         "rosters": [{"roster_id": 1, "is_mine": True, "player_ids": ["dart", "wr1", "qb2"]}, {"roster_id": 2, "is_mine": False, "player_ids": ["wr2"]}]}
    rows = trade_finder.find({**d, "_protected": {"dart": "IR"}})["rows"]
    assert all(r["give_id"] != "dart" for r in rows)


def test_never_drop_players_play_but_are_never_the_drop():
    from src.services.fantasy_locks import waivers
    def q(pid, points):
        return {"player_id": pid, "name": pid, "position": "WR", "decision_points": points, "weekly_points": points,
                "locked": False, "injury_status": None}
    mine = [q("starter", 10), q("keep", 5), q("spare", 4)]
    assert waivers(mine, [q("add", 12)], ["WR"], ["starter"], keep={"keep"})["moves"][0]["drop_id"] == "spare"
    assert waivers(mine, [q("add", 12)], ["WR"], ["starter"], keep={"keep", "spare"})["moves"] == []


def test_waiver_guidance_skips_never_drop_players_but_counts_them_in_the_lineup():
    from tests.test_waiver_guidance import p
    from src.services.waiver_guidance import guidance
    players = [p("qb", "QB", {6: 20, 7: 20}, True), p("wr", "WR", {6: 10, 7: 10}, True), p("rb", "RB", {6: 6, 7: 6}, True),
               p("bench", "WR", {6: 2, 7: 2}, True), p("fa_rb", "RB", {6: 9, 7: 9}, False),
               p("k", "K", {}, True, weekly=7.0), p("k2", "K", {}, True, weekly=5.0), p("fa_k", "K", {}, False, weekly=9.0)]
    mine = [x["player_id"] for x in players if x["roster_ids"]]
    slots = ["QB", "WR", "FLEX", "K", "BN", "BN", "BN"]
    rows = {r["add_id"]: r for r in guidance(players, mine, set(mine), slots, keep={"bench", "k2"})["rows"]}
    assert rows["fa_rb"]["drop_id"] not in ("bench", "k2") and rows["fa_k"]["drop_id"] == "k"
