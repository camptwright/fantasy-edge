from src.data import espn_injuries
import httpx
import pytest


def test_professional_sports_and_paths_are_explicit():
    assert espn_injuries._PATHS == {
        "nfl": "football/nfl", "nba": "basketball/nba", "mlb": "baseball/mlb", "nhl": "hockey/nhl"
    }


def test_extracts_athlete_id_from_public_player_link():
    assert espn_injuries.athlete_id({"links": [{"href": "https://www.espn.com/nfl/player/_/id/2578570/jacoby-brissett"}]}) == "2578570"
    assert espn_injuries.athlete_id({"links": []}) is None


@pytest.mark.parametrize("status,payload", [(503, {}), (200, {"error": "missing injuries"})])
async def test_failed_feed_cannot_publish_partial_success(monkeypatch, status, payload):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    monkeypatch.setattr(espn_injuries.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await espn_injuries.fetch_injury_reports()
