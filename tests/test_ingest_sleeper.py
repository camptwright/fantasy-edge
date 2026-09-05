"""src/ingest/sleeper.py's multi-sport plumbing.

Full account sync (_sync_sport) makes half a dozen sequential live Sleeper
API calls per sport and isn't mocked here - this covers the two things that
actually changed when Sleeper sync went from NFL-only to
settings.sleeper_sports: the persisted sport column, and the sport-list
invariant the rest of the app depends on.
"""

from __future__ import annotations

import httpx

from config.settings import get_settings
from src.ingest import sleeper as sleeper_module
from src.ingest.sleeper import _sync_sport, _upsert_league, sync_sleeper_account
from src.models.sleeper import SleeperLeague


def test_sleeper_sports_is_a_subset_of_supported_sports():
    """Every sport Sleeper is synced for must also be a sport the rest of
    the app (ingestion, API, scheduler) actually supports - a mismatch here
    would mean syncing a sport nothing else recognizes."""
    settings = get_settings()
    assert set(settings.sleeper_sports) <= set(settings.supported_sports)


async def test_upsert_league_persists_the_sport_column(db):
    league = {
        "league_id": "123456789", "name": "Test League", "season": "2026",
        "status": "in_season", "roster_positions": ["PG", "SG"], "settings": {}, "scoring_settings": {},
    }
    await _upsert_league(db, league, "nba")
    await db.flush()

    row = await db.get(SleeperLeague, "123456789")
    assert row.sport == "nba"


async def test_upsert_league_updates_sport_on_conflict(db):
    league = {
        "league_id": "987654321", "name": "Reused League Id", "season": "2026",
        "status": "in_season", "roster_positions": [], "settings": {}, "scoring_settings": {},
    }
    await _upsert_league(db, league, "nfl")
    await db.flush()
    await _upsert_league(db, {**league, "name": "Reused League Id (updated)"}, "nfl")
    await db.flush()

    row = await db.get(SleeperLeague, "987654321")
    assert row.sport == "nfl"
    assert row.name == "Reused League Id (updated)"


async def test_sync_sport_falls_back_to_season_when_league_season_is_absent(db):
    """FOUND LIVE 2026-09-05: verified against the real endpoint - MLB and
    NHL's /state response has no league_season key at all (only NFL/NBA
    carry it); both still carry season, identical to league_season on the
    sports that have both. Before this fix, a bare state["league_season"]
    raised KeyError on the third configured sport - and since
    sync_sleeper_account only commits once at the end of the sport loop,
    that discarded every sport's already-fetched data, not just the
    failing one."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/state/mlb"):
            return httpx.Response(200, json={"season": "2026", "week": 23, "season_type": "regular"})
        if request.url.path.endswith("/user/u1/leagues/mlb/2026"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.sleeper.app/v1")
    try:
        result = await _sync_sport(db, client, {"user_id": "u1"}, "mlb")
    finally:
        await client.aclose()
    # week comes from state["leg"], which MLB's real /state response also
    # doesn't carry - defaults to 1, same as _sync_sport's own `or 1` fallback.
    assert result == {"leagues": 0, "season": 2026, "week": 1}


async def test_sync_sleeper_account_persists_earlier_sports_when_a_later_sport_fails(db, monkeypatch):
    """A later sport's ingest failing must not discard an earlier sport's
    already-fetched leagues - the exact live failure mode this fixes (NFL
    leagues were fetched successfully every cycle, but MLB's KeyError
    crashed the task before the single end-of-loop commit ever ran)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "sleeper_username", "testuser", raising=False)
    monkeypatch.setattr(settings, "sleeper_sports", ("nfl", "mlb"), raising=False)

    async def fake_get(self, path, *args, **kwargs):
        return httpx.Response(200, json={"user_id": "u1"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def fake_sync_sport(db, client, user, sport):
        if sport == "nfl":
            await _upsert_league(
                db,
                {
                    "league_id": "sleeper-isolation-test", "name": "L", "season": "2026",
                    "status": "in_season", "roster_positions": [], "settings": {}, "scoring_settings": {},
                },
                "nfl",
            )
            return {"leagues": 1, "season": 2026, "week": 1}
        raise RuntimeError("boom")

    monkeypatch.setattr(sleeper_module, "_sync_sport", fake_sync_sport)

    results = await sync_sleeper_account(db)

    assert results["nfl"] == {"leagues": 1, "season": 2026, "week": 1}
    assert "error" in results["mlb"]
    row = await db.get(SleeperLeague, "sleeper-isolation-test")
    assert row is not None
