import asyncio

import pytest

from src.services import parlay_ai, parlay_generator as pg

TABLE = {"same_player|WR:receiving_yards|WR:receptions": {"rho": 0.7, "n": 2000},
         "teammate|QB:passing_yards|WR:receiving_yards": {"rho": 0.25, "n": 2000}}


def row(key, player, pos, stat, game, team, opp, fair, offers, line=4.5, books=4):
    return {"key": key, "player": player, "player_id": key.split(":")[0], "position": pos, "stat": stat, "line": line,
            "fair_over": fair, "books": books, "game_id": game, "game_time": "2026-10-18T17:00:00+00:00",
            "matchup": f"{opp} @ {team}", "sport": "nfl", "team": team, "opponent": opp,
            "offers": [{"book": b, "line": line, "over": o, "under": u} for b, o, u in offers],
            "hit": {"l10": {"hits": 7, "games": 10}}, "dvp": {"rank": 3, "teams": 32}, "engine": None}


ROWS = [
    row("a:g1:receptions", "Wide One", "WR", "receptions", "g1", "KC", "BUF", 0.55, [("dk", 110, -135), ("fd", 100, -120)]),
    row("a:g1:receiving_yards", "Wide One", "WR", "receiving_yards", "g1", "KC", "BUF", 0.52, [("dk", 105, -125)], line=60.5),
    row("q:g1:passing_yards", "Quarter Back", "QB", "passing_yards", "g1", "KC", "BUF", 0.5, [("dk", -110, -110)], line=250.5),
    row("b:g2:rushing_yards", "Running Back", "RB", "rushing_yards", "g2", "MIA", "NYJ", 0.6, [("dk", -120, 100), ("fd", -110, -110)], line=70.5),
    row("c:g3:receptions", "Tight End", "TE", "receptions", "g3", "DAL", "PHI", 0.45, [("dk", 140, -170), ("fd", 120, -150)], line=3.5),
]


def test_legs_are_priced_per_book_at_the_main_line():
    legs = pg.legs_from_board(ROWS)
    leg = next(x for x in legs if x["id"] == "a:g1:receptions:over:dk")
    assert leg["fair"] == 0.55 and leg["ev"] == pytest.approx(0.55 * 2.1 - 1, abs=1e-4)
    assert next(x for x in legs if x["id"] == "a:g1:receptions:under:fd")["fair"] == pytest.approx(0.45)


def test_cross_game_value_parlay_has_exact_ev_at_the_product_price():
    out = pg.generate(ROWS, pg.Constraints(legs=3, mode="value"), table=TABLE)
    best = out["parlays"][0]
    assert out["status"] == "built" and best["book"] == "dk"
    assert len({leg["game_id"] for leg in best["legs"]}) == 3 and not best["same_game"]
    assert best["probability"] == pytest.approx(best["independent_probability"])
    assert best["ev"] == pytest.approx(best["probability"] * best["decimal"] - 1, abs=1e-3)
    assert all(len({leg["book"] for leg in p["legs"]}) == 1 for p in out["parlays"])


def test_same_game_correlation_raises_the_joint_probability_and_withholds_ev():
    legs = [x for x in pg.legs_from_board(ROWS) if x["id"] in ("a:g1:receptions:over:dk", "a:g1:receiving_yards:over:dk")]
    p = pg.price(legs, TABLE)
    assert p["same_game"] and p["ev"] is None
    assert p["probability"] > p["independent_probability"] + 0.1
    flipped = [legs[0], {**legs[1], "side": "under", "fair": 0.48}]
    assert pg.joint_probability(flipped, TABLE) < 0.55 * 0.48


def test_constraints_filter_and_one_prop_never_gets_both_sides():
    out = pg.generate(ROWS, pg.Constraints(legs=2, side="over", teams=["KC"], same_game=True), table=TABLE)
    for parlay in out["parlays"]:
        assert all(leg["side"] == "over" and "KC" in (leg["team"], leg["opponent"]) for leg in parlay["legs"])
        assert len({leg["row"] for leg in parlay["legs"]}) == len(parlay["legs"])
    assert pg.generate(ROWS, pg.Constraints(legs=4, books=["fd"]), table=TABLE)["status"] == "constraints_unmet"
    # Three games at DraftKings cannot fill four different-game legs: retried with same-game legs, and said so.
    relaxed = pg.generate(ROWS, pg.Constraints(legs=4, books=["dk"]), table=TABLE)
    assert relaxed["relaxed"] == "same_game" and relaxed["parlays"][0]["same_game"]
    assert "relaxed" not in pg.generate(ROWS, pg.Constraints(legs=4, books=["dk"]), table=TABLE, relax=False)
    assert pg.generate(ROWS, pg.Constraints(stats=["passing_touchdowns"]), table=TABLE)["status"] == "no_candidates"


def test_safe_mode_prefers_likely_legs():
    out = pg.generate(ROWS, pg.Constraints(legs=2, mode="safe"), table=TABLE)
    assert min(leg["fair"] for leg in out["parlays"][0]["legs"]) >= 0.55


def test_keywords_parse_common_phrasings():
    k = parlay_ai.keywords("Safe 4-leg parlay, overs only, receivers, same game")
    assert k == {"legs": 4, "mode": "safe", "side": "over", "same_game": True, "stats": ["receptions", "receiving_yards"]}
    assert parlay_ai.keywords("three leg value unders on passing yards") == {"legs": 3, "mode": "value", "side": "under", "stats": ["passing_yards"]}


def test_grounding_drops_what_the_request_does_not_say():
    teams = {"KC": "Kansas City Chiefs", "BUF": "Buffalo Bills", "MIA": "Miami Dolphins"}
    players = ["Travis Kelce", "Josh Allen", "Davis Allen", "Tyreek Hill"]
    raw = {"legs": 9, "mode": "safe", "side": "over", "same_game": True, "teams": ["KC", "BUF", "MIA"],
           "players": ["Tyreek Hill"], "stats": ["bogus", "passing_yards", "receptions"]}
    # No count, side, game or stat words in the text: only the mode, named teams and named player survive.
    g = parlay_ai.ground(raw, "safe chiefs and bills parlay with Josh Allen", teams, players)
    assert g == {"mode": "safe", "teams": ["BUF", "KC"], "players": ["Josh Allen"]}
    g = parlay_ai.ground(raw, "6 leg same game parlay, overs on catches for Allen", teams, players)
    assert g == {"legs": 6, "mode": "safe", "side": "over", "same_game": True, "stats": ["receptions"], "players": ["Davis Allen", "Josh Allen"]}
    assert parlay_ai.ground({"exclude_players": ["Kelce"]}, "no Kelce", teams, players) == {"exclude_players": ["Travis Kelce"]}


def test_interpret_falls_back_to_keywords_when_the_model_is_down(monkeypatch):
    async def down(text, teams):
        raise ValueError("offline")
    monkeypatch.setattr(parlay_ai, "_model", down)
    out = asyncio.run(parlay_ai.interpret("2 leg unders for the Dolphins", {"MIA": "Miami Dolphins"}, []))
    assert out["ai"]["used"] is False and out["constraints"] == {"legs": 2, "side": "under", "teams": ["MIA"]}


def test_interpret_lets_text_keywords_beat_the_model(monkeypatch):
    async def model(text, teams):
        return {"legs": 5, "side": "under", "mode": "balanced", "teams": ["KC"]}
    monkeypatch.setattr(parlay_ai, "_model", model)
    out = asyncio.run(parlay_ai.interpret("3 leg overs", {"KC": "Kansas City Chiefs"}, []))
    assert out["ai"]["used"] and out["constraints"] == {"legs": 3, "side": "over", "mode": "balanced"}


def test_model_side_is_dropped_when_the_text_names_none(monkeypatch):
    async def model(text, teams):
        return {"legs": 4, "side": "over", "mode": "value"}
    monkeypatch.setattr(parlay_ai, "_model", model)
    out = asyncio.run(parlay_ai.interpret("4 leg value parlay", {}, []))
    assert out["constraints"] == {"legs": 4, "mode": "value"}


def test_named_players_are_required_legs_not_the_only_players():
    out = pg.generate(ROWS, pg.Constraints(legs=3, players=["Running Back"]), table=TABLE)
    for parlay in out["parlays"]:
        names = [leg["player"] for leg in parlay["legs"]]
        assert names.count("Running Back") == 1 and len(names) == 3


def test_value_mode_does_not_score_correlation_as_value():
    legs = [x for x in pg.legs_from_board(ROWS) if x["id"] in ("a:g1:receptions:over:dk", "a:g1:receiving_yards:over:dk")]
    joint = pg.joint_probability(legs, TABLE)
    assert pg.objective(legs, "value", joint) == pg.objective(legs, "value", pg.joint_probability(legs, {}))
