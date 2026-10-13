"""NFL team model v2: shared math, closing-line choice, live replay and signal use."""

from datetime import datetime, timedelta, timezone

import pytest

from src.ingest.identity import resolve_team
from src.models.facts import Game, TeamMarketLine
from src.services import team_model, team_model_serving

P = team_model.Params(k=0.4, resist=1.5, reversion=0.3, hfa=2.0, rest=0.15, sigma=13.0, mr_mid=2.0, mr_steep=3.0, mr_floor=0.8)


def test_expected_margin_has_home_field_and_clipped_rest():
    assert team_model.expected_margin(P, 3.0, 1.0) == 4.0
    assert team_model.expected_margin(P, 3.0, 1.0, neutral=True) == 2.0
    assert team_model.expected_margin(P, 0.0, 0.0, rest_diff=20) == pytest.approx(2.0 + 0.15 * 7)


def test_update_is_zero_sum_and_resists_when_the_market_was_closer():
    h, a = team_model.update(P, 0.0, 0.0, expected=3.0, margin=17.0, closing_spread=None)
    assert h > 0 and h + a == pytest.approx(0.0)
    h2, _ = team_model.update(P, 0.0, 0.0, expected=3.0, margin=17.0, closing_spread=14.0)
    assert h2 > h  # market said 14, model said 3: the model learns faster
    assert team_model.update(P, 0.0, 0.0, expected=7.0, margin=7.0, closing_spread=3.0) == (0.0, 0.0)


def test_small_disagreements_collapse_to_the_market_and_large_ones_keep_an_opinion():
    assert team_model.regress_to_market(P, 3.5, 3.0) == pytest.approx(3.0, abs=0.01)
    far = team_model.regress_to_market(P, 10.0, 3.0)
    assert 3.0 < far < 10.0 and far == pytest.approx(3.0 + 0.2 * 7.0, abs=0.05)
    assert team_model.regress_to_market(P, 10.0, None) == 10.0
    assert team_model.win_probability(P, 0.0) == pytest.approx(0.5)
    assert team_model.cover_probability(P, -3.0, 3.0) == pytest.approx(0.5)


def test_shipped_artifact_covers_all_teams_and_beat_the_serving_elo_out_of_sample():
    art = team_model.load()
    assert len(art["ratings"]) == 32 and "LAR" in art["ratings"] and "LA" not in art["ratings"]
    m = art["evidence"]["test_metrics"]
    assert m["rebuilt_raw"]["brier"] < m["serving_elo"]["brier"]
    assert art["version"].startswith("nfl_team_model_v2:")


async def _game(db, home, away, when, **kw):
    g = Game(sport="nfl", season=2026, game_type="REG", game_time=when, home_team_id=home.id, away_team_id=away.id, **kw)
    db.add(g)
    await db.flush()
    return g


async def test_replay_uses_the_close_and_ignores_post_kickoff_quotes(db):
    kc, lac = await resolve_team(db, "Kansas City Chiefs"), await resolve_team(db, "Los Angeles Chargers")
    start = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)
    g = await _game(db, kc, lac, start, status="final", home_score=30, away_score=10)
    db.add(TeamMarketLine(game_id=g.id, market="spread", side="home", line=-3.0, source="pinnacle", line_type="live", observed_at=start - timedelta(hours=1)))
    db.add(TeamMarketLine(game_id=g.id, market="spread", side="home", line=-12.0, source="pinnacle", line_type="live", observed_at=start + timedelta(hours=1)))
    db.add(TeamMarketLine(game_id=g.id, market="spread", side="home", line=-6.5, source="nflverse", line_type="closing", observed_at=start + timedelta(days=1)))
    await db.commit()
    assert (await team_model_serving.market_spreads(db, [g]))[g.id] == 6.5  # archived close wins
    s = await team_model_serving.state(db, now=start + timedelta(days=2))
    base = team_model.load()
    assert s["replayed_games"] == 1 and s["season"] == 2026
    before = (1 - base["params"].reversion) * (base["ratings"]["KC"] - base["ratings"]["LAC"])
    assert s["ratings"]["KC"] - s["ratings"]["LAC"] > before  # a 20-point home win moves KC up


async def test_nfl_signals_use_the_team_model(db):
    from tests.test_api_sportsbook import _client
    from src.api.main import app
    kc, lac = await resolve_team(db, "Kansas City Chiefs"), await resolve_team(db, "Los Angeles Chargers")
    now = datetime.now(timezone.utc)
    g = await _game(db, kc, lac, now + timedelta(days=1), status="scheduled")
    for side, price in (("home", -150), ("away", 130)):
        db.add(TeamMarketLine(game_id=g.id, market="moneyline", side=side, price_american=price, source="theodds", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=g.id, market="spread", side="home", line=-3.0, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=g.id, market="spread", side="away", line=3.0, price_american=-110, source="pinnacle", line_type="live", observed_at=now))
    await db.commit()
    client = await _client(db)
    try:
        rows = (await client.get("/signals?sport=nfl")).json()
    finally:
        app.dependency_overrides.clear()
    ml = next(r for r in rows if r["market"] == "moneyline" and r["side"] == "home")
    assert ml["model_version"].startswith("nfl_team_model_v2:") and ml["team_model"]["market_margin"] == 3.0
    assert ml["actionable"] is False  # no version-bound validation: research only
    spread = next(r for r in rows if r["market"] == "spread" and r["side"] == "home")
    assert 0.3 < spread["model_probability"] < 0.7  # regressed to the same spread: near a coin flip


async def test_team_projections_endpoint_lists_ratings_and_upcoming_games(db):
    from tests.test_api_sportsbook import _client
    from src.api.main import app
    kc, lac = await resolve_team(db, "Kansas City Chiefs"), await resolve_team(db, "Los Angeles Chargers")
    await _game(db, kc, lac, datetime.now(timezone.utc) + timedelta(days=2), status="scheduled")
    await db.commit()
    client = await _client(db)
    try:
        body = (await client.get("/team-projections/nfl")).json()
    finally:
        app.dependency_overrides.clear()
    assert body["status"] == "research" and len(body["ratings"]) == 32  # NFL lists every rated team
    assert body["games"][0]["home"] == "KC" and body["games"][0]["market_margin"] is None
    assert body["evidence"]["model_brier"] < body["evidence"]["previous_elo_brier"]


def test_nfl_lab_market_blend_reuses_frozen_probabilities():
    from src.services.nfl_lab_registry import MARKET_WEIGHT, market_blend
    assert MARKET_WEIGHT == 0.85
    assert market_blend({"probability": 0.70, "market_probability": 0.50}) == pytest.approx(0.15 * 0.70 + 0.85 * 0.50)
    assert market_blend({"probability": 0.70, "market_probability": None}) is None


def test_scoring_split_points_sum_to_the_total_and_follow_offense_and_defense():
    s = team_model.ScoringParams(hfa=2.0)
    hp, ap = team_model.expected_points(s, 22.0, 3.0, 1.0, -1.0, -2.0)
    assert (hp, ap) == (22.0 + 3.0 + 2.0 + 1.0, 22.0 - 1.0 - 1.0 - 1.0)
    ratings = {}
    league = team_model.update_scoring(s, ratings, "KC", "LAC", 22.0, (24.0, 20.0), (34.0, 20.0), None)
    assert ratings["KC"][0] > 0 and ratings["LAC"][1] < 0 and league > 22.0  # KC scored more than expected
    assert team_model.implied_points(47.0, 3.0) == (25.0, 22.0)
    assert team_model.regress_total(team_model.ScoringParams(mr_floor=1.0), 51.0, 44.5) == 44.5


async def test_projection_carries_team_points_and_market_total(db):
    kc, lac = await resolve_team(db, "Kansas City Chiefs"), await resolve_team(db, "Los Angeles Chargers")
    now = datetime.now(timezone.utc)
    g = await _game(db, kc, lac, now + timedelta(days=1), status="scheduled")
    db.add(TeamMarketLine(game_id=g.id, market="total", side="over", line=44.5, price_american=-110, source="pinnacle", line_type="live", observed_at=now - timedelta(minutes=5)))
    await db.commit()
    s = await team_model_serving.state(db, now=now)
    totals = await team_model_serving.market_totals(db, [g])
    row = team_model_serving.project(s, g, None, totals.get(g.id))
    assert row["market_total"] == 44.5 and row["home_points"] + row["away_points"] == pytest.approx(row["total"])
    assert row["home_points"] - row["away_points"] == pytest.approx(row["margin"])


async def test_stale_unfinished_games_are_repolled_by_date(db):
    from src.ingest.espn import stale_dates
    kc, lac = await resolve_team(db, "Kansas City Chiefs"), await resolve_team(db, "Los Angeles Chargers")
    now = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)
    await _game(db, kc, lac, datetime(2026, 9, 27, 0, 30, tzinfo=timezone.utc), status="in_progress")
    await _game(db, kc, lac, datetime(2026, 10, 12, 16, tzinfo=timezone.utc), status="in_progress")  # recent: still live
    await _game(db, kc, lac, datetime(2026, 9, 20, 17, tzinfo=timezone.utc), status="final", home_score=1, away_score=0)
    await db.commit()
    assert await stale_dates(db, "nfl", now=now) == ["20260926", "20260927"]


async def test_ncaaf_signals_keep_the_owner_override_and_attach_the_college_model(db):
    from tests.test_api_sportsbook import _client
    from src.api.main import app
    osu = await resolve_team(db, "Ohio State Buckeyes", sport="ncaaf")
    mich = await resolve_team(db, "Michigan Wolverines", sport="ncaaf")
    now = datetime.now(timezone.utc)
    g = Game(sport="ncaaf", season=2026, game_type="REG", status="scheduled", game_time=now + timedelta(days=1),
             home_team_id=osu.id, away_team_id=mich.id)
    db.add(g)
    await db.flush()
    from src.models.ratings import TeamRating
    db.add_all([TeamRating(team_id=osu.id, sport="ncaaf", rating=1600), TeamRating(team_id=mich.id, sport="ncaaf", rating=1500)])
    for side, price in (("home", -300), ("away", 240)):
        db.add(TeamMarketLine(game_id=g.id, market="moneyline", side=side, price_american=price, source="theodds", line_type="live", observed_at=now))
    await db.commit()
    client = await _client(db)
    try:
        rows = (await client.get("/signals?sport=ncaaf")).json()
        board = (await client.get("/team-projections/ncaaf")).json()
    finally:
        app.dependency_overrides.clear()
    home = next(r for r in rows if r["side"] == "home")
    assert home["team_model"]["version"].startswith("ncaaf_team_model_v1:") and 0.5 < home["team_model"]["probability"] < 1
    assert home["model_probability"] != home["team_model"]["probability"]  # serving keeps the Elo + approved override
    assert board["sport"] == "ncaaf" and board["games"][0]["home_name"] == osu.name
    assert [r["name"] for r in board["ratings"]] == [osu.name, mich.name]  # only stored teams are listed
    assert abs(board["ratings"][0]["offense"]) < 30  # centred, not the unidentified raw level
