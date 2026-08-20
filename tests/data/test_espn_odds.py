from src.data.providers.espn_api import parse_game_odds


def test_parse_game_odds_keeps_only_published_markets():
    rows = parse_game_odds({
        "id": "123", "date": "2026-09-01T00:00Z",
        "competitions": [{"odds": [{
            "spread": -3.5, "overUnder": 44.5,
            "homeTeamOdds": {"moneyLine": -150},
            "awayTeamOdds": {"moneyLine": 130},
        }]}],
    })
    assert {(r["market"], r["selection"]) for r in rows} == {
        ("total", "game"), ("spread", "home"), ("moneyline", "home"), ("moneyline", "away")
    }
    assert all(r["source"] == "espn" for r in rows)
