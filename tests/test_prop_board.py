from datetime import datetime, timedelta, timezone

import pytest

from src.services import prop_board
from src.utils.odds_math import remove_vig_two_way


def offer(book, line, over, under):
    return {"book": book, "line": line, "over": over, "under": under, "observed_at": "2026-10-11T12:00:00+00:00"}


def test_consensus_uses_the_most_quoted_line_and_averages_no_vig_probabilities():
    offers = [offer("draftkings", 4.5, -120, 100), offer("fanduel", 4.5, -110, -110),
              offer("betmgm", 4.5, -105, -115), offer("caesars", 5.5, 130, -160)]
    c = prop_board.consensus(offers)
    assert c["line"] == 4.5 and c["books"] == 3 and c["other_lines"] == [5.5]
    expected = sum(remove_vig_two_way(o, u)[0] for o, u in ((-120, 100), (-110, -110), (-105, -115))) / 3
    assert c["fair_over"] == pytest.approx(expected, abs=1e-4)
    assert c["best_over"] == {"book": "betmgm", "price": -105}
    assert c["best_under"] == {"book": "draftkings", "price": 100}
    assert c["ev_over"] == pytest.approx(c["fair_over"] * (1 + 100 / 105) - 1, abs=1e-3)
    assert c["ev_under"] == pytest.approx((1 - c["fair_over"]) * 2 - 1, abs=1e-3)


def test_one_sided_quotes_price_but_do_not_vote():
    c = prop_board.consensus([offer("draftkings", 0.5, -150, 120), offer("bovada", 0.5, -130, None)])
    assert c["books"] == 1 and c["quoted"] == 2
    assert c["best_over"] == {"book": "bovada", "price": -130}
    assert c["fair_over"] == pytest.approx(remove_vig_two_way(-150, 120)[0], abs=1e-4)


def test_no_two_sided_quote_means_no_fair_price():
    c = prop_board.consensus([offer("bovada", 49.5, -115, None)])
    assert c["fair_over"] is None and c["ev_over"] is None and c["best_over"]["price"] == -115


def test_hit_rates_count_strictly_over_the_line():
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)
    history = [(t - timedelta(days=7 * i), v, "BUF" if i % 3 == 0 else "MIA") for i, v in enumerate([60, 40, 55, 50.5, 70, 10, 90])]
    h = prop_board.hit_rates(history, 50.5, t - timedelta(days=30), "BUF")
    assert h["l5"] == {"hits": 3, "games": 5}  # 60, 55, 70; 50.5 is not over
    assert h["l10"] == {"hits": 4, "games": 7}
    assert h["season"] == {"hits": 3, "games": 5}  # the five games inside 30 days
    assert h["vs_opponent"] == {"hits": 2, "games": 3}  # 60, 50.5, 90
    assert h["last5"] == [60, 40, 55, 50.5, 70]


def test_dvp_rank_one_allows_the_most():
    ranks = prop_board.dvp_ranks({("A", "WR", "receptions"): [20, 22], ("B", "WR", "receptions"): [10], ("C", "WR", "receptions"): [15]})
    assert ranks[("A", "WR", "receptions")] == (1, 3) and ranks[("B", "WR", "receptions")] == (3, 3)


def board_row(key="p1:g1:receptions", ev_over=0.05, books=3, fair=0.55, line=4.5):
    return {"key": key, "player": "A Player", "stat": "receptions", "line": line, "books": books, "fair_over": fair,
            "ev_over": ev_over, "ev_under": -0.08, "best_over": {"book": "draftkings", "price": 110},
            "best_under": {"book": "fanduel", "price": -140}, "game_time": "2026-10-18T17:00:00+00:00"}


def test_tracker_freezes_value_picks_closes_them_then_grades():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    t = prop_board.track({}, {"rows": [board_row(), board_row("p2:g1:receptions", books=2)]}, {}, now)
    assert [p["id"] for p in t["picks"]] == ["p1:g1:receptions:over:4.5"]  # two books is too thin
    pick = t["picks"][0]
    assert pick["price"] == 110 and pick["fair"] == 0.55 and pick["close_fair"] == 0.55
    # Market moves toward the pick before kickoff: positive CLV against the price taken.
    t = prop_board.track(t, {"rows": [board_row(fair=0.6, ev_over=0.1)]}, {}, now + timedelta(days=1))
    assert len(t["picks"]) == 1 and t["picks"][0]["close_fair"] == 0.6 and t["picks"][0]["fair"] == 0.55
    assert t["summary"]["average_clv"] == pytest.approx(0.6 - 100 / 210, abs=1e-3)
    t = prop_board.track(t, {"rows": []}, {("p1", "g1", "receptions"): 6.0}, now + timedelta(days=4))
    assert t["picks"][0]["result"] == "win" and t["summary"]["units"] == pytest.approx(1.1)
    assert t["summary"]["roi"] == pytest.approx(1.1)


def test_tracker_does_not_close_after_kickoff_or_on_a_moved_line():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    t = prop_board.track({}, {"rows": [board_row()]}, {}, now)
    t = prop_board.track(t, {"rows": [board_row(fair=0.4, line=5.5)]}, {}, now + timedelta(hours=1))
    assert t["picks"][0]["close_fair"] == 0.55
    t = prop_board.track(t, {"rows": [board_row(fair=0.3)]}, {}, datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert t["picks"][0]["close_fair"] == 0.55


def test_unders_grade_and_pushes_are_not_counted():
    picks = [{"result": "push", "price": -110, "ev": 0.02}, {"result": "loss", "price": -110, "ev": 0.02}]
    s = prop_board.summary(picks)
    assert s["graded"] == 1 and s["units"] == -1
