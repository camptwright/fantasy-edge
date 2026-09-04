"""The sportsbook API surface (src/api/routers/sportsbook.py) - the contract
homelab-dashboard's Fantasy tile already expects.

get_db is overridden to yield the `db` fixture's own session directly,
rather than a second pooled engine built from production-shaped settings -
this app's lifespan is never started, so src.db.client.get_api_engine() is
never touched by these tests at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.db.client import get_db
from src.ingest.identity import resolve_team
from src.models.facts import Game, PlayerGameStat, PlayerPropLine, TeamMarketLine
from src.models.identity import Player
from src.models.ratings import TeamRating


async def _client(db):
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_props_returns_the_expected_shape_and_null_projection(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    player = Player(sport="nfl", full_name="Test Player", current_team_id=home.id)
    db.add(player)
    await db.flush()
    db.add(
        PlayerPropLine(
            player_id=player.id,
            stat_type="passing_yards",
            line=250.5,
            over_price_american=-110,
            under_price_american=-110,
            source="underdog",
            observed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/props?sport=nfl")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        row = body[0]
        assert row["player_name"] == "Test Player"
        assert row["team_name"] == home.name
        assert row["stat_type"] == "passing_yards"
        # No player-projection pipeline yet - null, not fabricated.
        assert row["projection"] is None
        assert row["edge_percent"] is None
    finally:
        app.dependency_overrides.clear()


async def test_props_distinct_on_returns_only_the_latest_line(db):
    """Constraint #7: props list endpoints must return only the latest
    observation per (player, stat_type, source), never duplicates."""
    home = await resolve_team(db, "Kansas City Chiefs")
    player = Player(sport="nfl", full_name="Duplicate Test", current_team_id=home.id)
    db.add(player)
    await db.flush()
    db.add(
        PlayerPropLine(
            player_id=player.id, stat_type="rushing_yards", line=50.5,
            source="underdog", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.add(
        PlayerPropLine(
            player_id=player.id, stat_type="rushing_yards", line=55.5,
            source="underdog", observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/props?sport=nfl")
        body = response.json()
        assert len(body) == 1, "DISTINCT ON must collapse to one row per identity key"
        assert body[0]["line"] == 55.5, "the latest observation must win"
    finally:
        app.dependency_overrides.clear()


async def test_signals_and_rankings_reflect_elo_ratings(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1600.0))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1400.0))
    game = Game(
        sport="nfl", espn_event_id="signal-test-1", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="home", price_american=-150, source="theodds", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="away", price_american=130, source="theodds", line_type="live", observed_at=now))
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/signals?sport=nfl")
        assert response.status_code == 200
        signals = response.json()
        assert len(signals) == 2
        home_signal = next(s for s in signals if "Chiefs" in s["selection"])
        assert home_signal["model_probability"] > 0.5, "the higher-rated home team must be favored"
        assert home_signal["fair_probability"] is not None, "both sides are priced, so vig removal must run"

        rankings_response = await client.get("/rankings/nfl")
        rankings = rankings_response.json()
        assert rankings[0]["team_name"] == home.name, "rankings must sort by rating descending"
    finally:
        app.dependency_overrides.clear()


async def test_rankings_rejects_an_unsupported_sport(db):
    client = await _client(db)
    try:
        response = await client.get("/rankings/wnba")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_totals_are_omitted_until_both_teams_are_qualified(db):
    """Fewer than MIN_GAMES_FOR_TOTALS games played - the scoring average
    isn't trustworthy yet, so /signals must omit the total rather than
    price it off a near-empty average (same discipline as the moneyline/
    spread branch omitting a brand-new team with no Elo history)."""
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1500.0, games_played=0))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1500.0, games_played=0))
    game = Game(
        sport="nfl", espn_event_id="signal-test-total-1", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(TeamMarketLine(game_id=game.id, market="total", side="over", line=45.5, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="total", side="under", line=45.5, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/signals?sport=nfl")
        signals = response.json()
        assert not any(s["market"] == "total" for s in signals)
    finally:
        app.dependency_overrides.clear()


async def test_totals_are_priced_once_both_teams_are_qualified(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1600.0, avg_points_scored=28.0, avg_points_allowed=20.0, games_played=5))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1400.0, avg_points_scored=22.0, avg_points_allowed=24.0, games_played=5))
    game = Game(
        sport="nfl", espn_event_id="signal-test-total-2", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    # Posted total well below the model's expected total should make the
    # Over the favored side.
    db.add(TeamMarketLine(game_id=game.id, market="total", side="over", line=30.0, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="total", side="under", line=30.0, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/signals?sport=nfl")
        signals = response.json()
        totals = [s for s in signals if s["market"] == "total"]
        assert len(totals) == 2
        over = next(s for s in totals if s["selection"].startswith("Over"))
        assert over["model_probability"] > 0.9
        assert over["fair_probability"] is not None
    finally:
        app.dependency_overrides.clear()


async def test_odds_history_returns_every_observation_in_order(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    game = Game(
        sport="nfl", espn_event_id="history-test-1", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    db.add(TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.0, price_american=-110, source="pinnacle", line_type="live", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.add(TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.5, price_american=-115, source="pinnacle", line_type="live", observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get(f"/odds/{game.id}/history")
        assert response.status_code == 200
        body = response.json()
        assert body["sport"] == "nfl"
        # Both observations, oldest first - this is the movement itself,
        # not a DISTINCT-ON latest-only listing.
        assert [row["line"] for row in body["lines"]] == [-3.0, -3.5]
    finally:
        app.dependency_overrides.clear()


async def test_props_carries_a_real_projection_once_qualified(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    player = Player(sport="nfl", full_name="Qualified Player", current_team_id=home.id)
    db.add(player)
    await db.flush()

    for i, value in enumerate([250.0, 275.0, 300.0, 225.0]):
        game = Game(
            sport="nfl", espn_event_id=f"props-test-{i}", season=2026,
            home_team_id=home.id, away_team_id=away.id, status="final",
        )
        db.add(game)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=game.id, stat_type="passing_yards", value=value))

    db.add(
        PlayerPropLine(
            player_id=player.id, stat_type="passing_yards", line=200.0,
            over_price_american=-110, under_price_american=-110,
            source="underdog", observed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/props?sport=nfl")
        row = response.json()[0]
        assert row["projection"] == pytest.approx(262.5, abs=0.01)
        # Line (200) is well below the 262.5 mean - the over should carry a
        # positive edge.
        assert row["edge_percent"] > 0
        # The under's own probability/edge (added for the parlay builder,
        # POST /parlays/build) must be the complement, not a repeat of the
        # over side's numbers.
        assert row["model_probability"] + row["under_model_probability"] == pytest.approx(1.0)
        assert row["under_edge_percent"] < 0

        best_response = await client.get("/props/best?sport=nfl")
        best = best_response.json()
        assert len(best["items"]) == 1
        assert best["items"][0]["player_name"] == "Qualified Player"
    finally:
        app.dependency_overrides.clear()


async def test_props_best_reports_the_gap_when_nothing_is_qualified(db):
    client = await _client(db)
    try:
        response = await client.get("/props/best")
        body = response.json()
        assert body["items"] == []
        assert "no props have a qualified projection" in body["note"]
    finally:
        app.dependency_overrides.clear()


async def test_odds_history_404s_for_an_unknown_game(db):
    client = await _client(db)
    try:
        response = await client.get("/odds/00000000-0000-0000-0000-000000000000/history")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_recommendations_reports_the_gap_when_nothing_has_been_generated(db):
    client = await _client(db)
    try:
        response = await client.get("/recommendations")
        body = response.json()
        assert body["narrative"] is None
        assert body["generated_at"] is None
        assert "no recommendation generated yet" in body["note"]
    finally:
        app.dependency_overrides.clear()


async def test_recommendations_returns_the_latest_snapshot(db):
    from src.models.governance import RecommendationSnapshot

    db.add(RecommendationSnapshot(narrative="Older narrative.", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db.add(RecommendationSnapshot(narrative="Newest narrative.", generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    await db.commit()

    client = await _client(db)
    try:
        response = await client.get("/recommendations")
        body = response.json()
        assert body["narrative"] == "Newest narrative."
    finally:
        app.dependency_overrides.clear()


async def test_build_parlay_combines_a_signal_and_a_prop_leg(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1600.0))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1400.0))
    game = Game(
        sport="nfl", espn_event_id="parlay-test-1", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="home", price_american=-150, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="away", price_american=130, source="pinnacle", line_type="live", observed_at=now))

    player = Player(sport="nfl", full_name="Parlay Test Player", current_team_id=home.id)
    db.add(player)
    await db.flush()
    for i, value in enumerate([250.0, 275.0, 300.0, 225.0]):
        stat_game = Game(
            sport="nfl", espn_event_id=f"parlay-test-stat-{i}", season=2026,
            home_team_id=home.id, away_team_id=away.id, status="final",
        )
        db.add(stat_game)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=stat_game.id, stat_type="passing_yards", value=value))
    prop = PlayerPropLine(
        player_id=player.id, stat_type="passing_yards", line=200.0,
        over_price_american=-110, under_price_american=-110,
        source="underdog", observed_at=now,
    )
    db.add(prop)
    await db.commit()

    client = await _client(db)
    try:
        signals_response = await client.get("/signals?sport=nfl")
        signal_id = next(s["id"] for s in signals_response.json() if s["selection"].startswith("Kansas City"))

        response = await client.post(
            "/parlays/build",
            json={"legs": [
                {"kind": "signal", "id": signal_id},
                {"kind": "prop", "id": str(prop.id), "side": "over"},
            ]},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["legs"]) == 2
        assert body["skipped_legs"] == []
        assert 0 < body["combined_probability"] < 1
        assert body["combined_price_american"] is not None
    finally:
        app.dependency_overrides.clear()


async def test_build_parlay_skips_an_unknown_leg_instead_of_erroring(db):
    client = await _client(db)
    try:
        response = await client.post(
            "/parlays/build",
            json={"legs": [{"kind": "signal", "id": "00000000-0000-0000-0000-000000000099"}]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["legs"] == []
        assert len(body["skipped_legs"]) == 1
        assert body["combined_probability"] is None
    finally:
        app.dependency_overrides.clear()
