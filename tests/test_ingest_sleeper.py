"""src/ingest/sleeper.py's multi-sport plumbing.

Full account sync (_sync_sport) makes half a dozen sequential live Sleeper
API calls per sport and isn't mocked here - this covers the two things that
actually changed when Sleeper sync went from NFL-only to
settings.sleeper_sports: the persisted sport column, and the sport-list
invariant the rest of the app depends on.
"""

from __future__ import annotations

from config.settings import get_settings
from src.ingest.sleeper import _upsert_league
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
