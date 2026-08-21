"""ESPN sync: one live smoke test plus offline unit tests for _upsert_event.

The live test is marked `live` because it makes a real network call. Run
explicitly with `pytest -m live`; excluded from the default suite. The
`_upsert_event` tests below construct fake event payloads directly and never
touch the network, so they run in the default suite like any other test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.espn import _upsert_event, sync_scoreboard
from src.ingest.identity import resolve_team
from src.models.facts import Game
from src.models.governance import IngestionRun


@pytest.mark.live
async def test_sync_records_a_run_and_creates_fixtures(db):
    await sync_scoreboard(db, days_ahead=7)

    run = await db.scalar(
        select(IngestionRun).where(IngestionRun.source == "espn").limit(1)
    )
    assert run is not None and run.status == "succeeded"

    games = await db.scalar(
        select(func.count()).select_from(Game).where(Game.espn_event_id.isnot(None))
    )
    assert games > 0, "ESPN returned no events for the next seven days"


async def test_upsert_event_never_persists_a_partial_new_game(db):
    """A malformed event (missing the away competitor entirely) for a Game
    that has never been seen before must leave no trace - not a Game row
    with a NULL away_team_id, and not silence: run.detail must say so."""
    event = {
        "id": "999999",
        "date": "2026-09-10T20:15Z",
        "season": {"year": 2026},
        "week": {"number": 2},
        "competitions": [
            {
                "status": {"type": {"state": "pre"}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "0",
                        "team": {"displayName": "Kansas City Chiefs"},
                    }
                ],
            }
        ],
    }
    run = IngestionRun(source="espn")

    result = await _upsert_event(db, event, run)

    assert result is None
    assert run.detail is not None and "999999" in run.detail

    count = await db.scalar(
        select(func.count()).select_from(Game).where(Game.espn_event_id == "999999")
    )
    assert count == 0, "a malformed new event must not leave a partial Game row behind"


async def test_upsert_event_existing_game_keeps_valid_teams_when_poll_is_incomplete(db):
    """A Game that was already fully resolved by a prior successful sync
    must not have its team assignment clobbered by a later poll that only
    returns one competitor - but its schedule/status/score fields, which
    don't depend on team resolution, should still update."""
    kc = await resolve_team(db, "Kansas City Chiefs")
    lac = await resolve_team(db, "Los Angeles Chargers")
    existing = Game(
        espn_event_id="888888",
        season=2026,
        week=1,
        status="scheduled",
        home_team_id=kc.id,
        away_team_id=lac.id,
    )
    db.add(existing)
    await db.flush()

    event = {
        "id": "888888",
        "date": "2026-09-10T20:15Z",
        "season": {"year": 2026},
        "week": {"number": 1},
        "competitions": [
            {
                "status": {"type": {"state": "in"}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "10",
                        "team": {"displayName": "Kansas City Chiefs"},
                    }
                    # away competitor missing this poll - e.g. a transient
                    # ESPN payload glitch.
                ],
            }
        ],
    }
    run = IngestionRun(source="espn")

    result = await _upsert_event(db, event, run)

    assert result is not None and result.id == existing.id
    assert result.home_team_id == kc.id and result.away_team_id == lac.id, (
        "existing valid team IDs must survive an incomplete poll"
    )
    assert result.status == "in_progress", "status should still update from this poll"
    assert result.home_score == 10, "home score is independent of team resolution"
    assert run.detail is not None and "888888" in run.detail
