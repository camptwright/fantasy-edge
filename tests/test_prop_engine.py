"""Engine prop probabilities: empirical ratio CDF and the research board."""

from datetime import datetime, timedelta, timezone

import pytest

from src.services import prop_engine

ART = {"stats": {"receiving_yards": {"edges": [10.0, 30.0], "quantiles": [[0, 1, 2]] * 2 + [[0.0, 1.0, 2.0]]}}}


def test_over_probability_reads_the_ratio_cdf_for_the_projection_bucket():
    # ratios uniform on [0, 2] for a 50-yard projection: P(actual > 50) = 0.5, P(> 75) = 0.25
    assert prop_engine.over_probability("receiving_yards", 50.0, 50.0, ART) == pytest.approx(0.5)
    assert prop_engine.over_probability("receiving_yards", 50.0, 75.0, ART) == pytest.approx(0.25)
    assert prop_engine.over_probability("receiving_yards", 50.0, 200.0, ART) == 0.0
    assert prop_engine.over_probability("rushing_yards", 50.0, 40.5, ART) is None
    assert prop_engine.over_probability("receiving_yards", 0.0, 0.5, ART) is None


def test_shipped_artifact_has_three_stats_and_records_that_the_market_won():
    art = prop_engine.load()
    assert set(art["stats"]) == set(prop_engine.STATS)
    for stat, ev in art["evidence"].items():
        assert ev["market"]["brier"] < ev["empirical"]["brier"] < ev["history"]["brier"]


async def test_engine_board_ranks_disagreements_on_upcoming_props(db, monkeypatch):
    from src.api.main import app
    from src.ingest.identity import resolve_team
    from src.models.facts import Game, PlayerPropLine
    from src.models.identity import Player
    from tests.test_api_sportsbook import _client
    det, gb = await resolve_team(db, "Detroit Lions"), await resolve_team(db, "Green Bay Packers")
    now = datetime.now(timezone.utc)
    g = Game(sport="nfl", season=2026, week=6, game_type="REG", status="scheduled", game_time=now + timedelta(days=1),
             home_team_id=det.id, away_team_id=gb.id)
    p = Player(sport="nfl", full_name="Amon-Ra St. Brown", position="WR")
    db.add_all([g, p])
    await db.flush()
    db.add(PlayerPropLine(player_id=p.id, game_id=g.id, stat_type="receiving_yards", line=75.5, over_price_american=-115,
                          under_price_american=-105, source="pinnacle", observed_at=now))
    await db.commit()

    async def checkpoint(_db):
        return {"status": "research", "players": {str(p.id): {"6": {"game_id": str(g.id), "stats": {"receiving_yards": 50.0}}}}}
    monkeypatch.setattr("src.services.engine_research.latest", checkpoint)
    monkeypatch.setattr(prop_engine, "load", lambda: ART)
    client = await _client(db)
    try:
        body = (await client.get("/props/engine-board")).json()
    finally:
        app.dependency_overrides.clear()
    row = body["rows"][0]
    assert body["compared"] == 1 and row["engine_projection"] == 50.0
    assert row["engine_over_probability"] == pytest.approx(0.245, abs=0.01) and row["difference"] < 0
