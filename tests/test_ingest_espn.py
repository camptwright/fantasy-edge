"""ESPN sync: one live smoke test plus offline unit tests for _upsert_event.

The live test is marked `live` because it makes a real network call. Run
explicitly with `pytest -m live`; excluded from the default suite. The
`_upsert_event` tests below construct fake event payloads directly and never
touch the network, so they run in the default suite like any other test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.espn import _game_type_and_week, _upsert_event, sync_scoreboard
from src.ingest.identity import resolve_team
from src.models.facts import Game
from src.models.governance import IngestionRun


@pytest.mark.live
async def test_sync_records_a_run_and_creates_fixtures(db):
    await sync_scoreboard(db, days_ahead=7)

    run = await db.scalar(
        select(IngestionRun).where(IngestionRun.source == "espn_nfl").limit(1)
    )
    assert run is not None and run.status == "succeeded"

    games = await db.scalar(
        select(func.count()).select_from(Game).where(Game.espn_event_id.isnot(None))
    )
    assert games > 0, "ESPN returned no events for the next seven days"


def test_game_type_and_week_mapping():
    """Pins ESPN's season.type/week.number -> nflverse's game_type/week
    vocabulary, verified live 2026-08-22 against the real ESPN scoreboard
    endpoint (season.type 1/2/3 = preseason/regular-season/post-season) and
    against the real 2024-season playoff dates (postseason week.number
    1=Wild Card, 2=Divisional, 3=Conference Championship, 4=Pro Bowl,
    5=Super Bowl), cross-checked against the live DB's own
    season/week/game_type rows.
    """
    # Preseason and regular season: game_type is new/normalized, week
    # passes through unchanged - ESPN's own numbering already matches
    # nflverse's for these phases.
    assert _game_type_and_week(
        {"season": {"type": 1, "year": 2025}, "week": {"number": 2}}
    ) == ("PRE", 2)
    assert _game_type_and_week(
        {"season": {"type": 2, "year": 2025}, "week": {"number": 1}}
    ) == ("REG", 1)

    # Postseason, modern (17-game) era: nflverse uses weeks 19-22.
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2024}, "week": {"number": 1}}
    ) == ("WC", 19)
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2024}, "week": {"number": 2}}
    ) == ("DIV", 20)
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2024}, "week": {"number": 3}}
    ) == ("CON", 21)
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2024}, "week": {"number": 5}}
    ) == ("SB", 22)

    # Postseason, legacy (16-game) era: nflverse uses weeks 18-21 - a
    # DIFFERENT base, proving this isn't a single hardcoded offset.
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2019}, "week": {"number": 1}}
    ) == ("WC", 18)
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2019}, "week": {"number": 5}}
    ) == ("SB", 21)

    # Pro Bowl (week 4) and any unrecognised postseason week: left
    # deliberately unmapped rather than guessed.
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2024}, "week": {"number": 4}}
    ) == (None, None)


def test_game_type_and_week_ncaaf_uses_raw_week_not_nfl_postseason_rounds():
    """NCAAF has no nflverse equivalent to align postseason week numbering
    to (dozens of bowls plus a multi-round CFP, not four fixed rounds), so
    its postseason must stay ESPN's own raw week.number under game_type
    "POST" - never NFL's WC/DIV/CON/SB vocabulary."""
    assert _game_type_and_week(
        {"season": {"type": 2, "year": 2025}, "week": {"number": 10}}, "ncaaf"
    ) == ("REG", 10)
    assert _game_type_and_week(
        {"season": {"type": 3, "year": 2025}, "week": {"number": 1}}, "ncaaf"
    ) == ("POST", 1)


async def test_upsert_event_sets_game_type_and_normalizes_postseason_week(db):
    """The Game row _upsert_event produces must carry game_type (never set
    before this fix) and, for a postseason event, nflverse's week
    numbering rather than ESPN's own 1-5."""
    event = {
        "id": "espn-postseason-week-test",
        "date": "2025-01-11T21:30Z",
        "season": {"year": 2024, "type": 3},
        "week": {"number": 1},
        "competitions": [
            {
                "status": {"type": {"state": "post"}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "27",
                        "team": {"displayName": "Houston Texans"},
                    },
                    {
                        "homeAway": "away",
                        "score": "32",
                        "team": {"displayName": "Los Angeles Chargers"},
                    },
                ],
            }
        ],
    }
    run = IngestionRun(source="espn")

    result = await _upsert_event(db, event, run)

    assert result is not None
    assert result.game_type == "WC"
    assert result.week == 19, "ESPN's postseason week 1 must normalize to nflverse's week 19"


async def test_upsert_event_resolves_ncaaf_teams_and_tags_the_game_sport(db):
    """A brand-new NCAAF event must resolve teams against ncaaf.yaml (not
    nfl.yaml) and stamp sport="ncaaf" on the created Game - the override of
    the original NFL-only data-foundation plan (see CLAUDE.md)."""
    event = {
        "id": "ncaaf-espn-test-1",
        "date": "2026-09-05T23:30Z",
        "season": {"year": 2026, "type": 2},
        "week": {"number": 1},
        "competitions": [
            {
                "status": {"type": {"state": "pre"}},
                "competitors": [
                    {"homeAway": "home", "score": "0", "team": {"displayName": "Ohio State Buckeyes"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "Alabama Crimson Tide"}},
                ],
            }
        ],
    }
    run = IngestionRun(source="espn")

    result = await _upsert_event(db, event, run, sport="ncaaf")

    assert result is not None
    assert result.sport == "ncaaf"

    home = await resolve_team(db, "Ohio State Buckeyes", sport="ncaaf")
    assert result.home_team_id == home.id


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


async def test_upsert_event_existing_game_keeps_omitted_side_score_when_poll_is_incomplete(
    db,
):
    """Regression test: an existing Game already carries real scores on
    BOTH sides (e.g. from an earlier successful poll mid-game). A later
    poll whose competitor list omits one side entirely (not merely a side
    with no numeric score - actually absent from `competitors`) must leave
    that omitted side's DB score exactly as it was; only the side that was
    actually present this poll may update.

    This is distinct from
    test_upsert_event_existing_game_keeps_valid_teams_when_poll_is_incomplete
    above, which seeds a Game with no prior scores at all (both start as
    None), so it cannot detect a real prior value getting wiped to None -
    None overwritten with None is indistinguishable from "left alone" in
    that test. Here both sides start with a genuine non-None score so a
    wipe is observable.
    """
    kc = await resolve_team(db, "Kansas City Chiefs")
    lac = await resolve_team(db, "Los Angeles Chargers")
    existing = Game(
        espn_event_id="777777",
        season=2026,
        week=1,
        status="in_progress",
        home_team_id=kc.id,
        away_team_id=lac.id,
        home_score=17,
        away_score=14,
    )
    db.add(existing)
    await db.flush()

    event = {
        "id": "777777",
        "date": "2026-09-10T20:15Z",
        "season": {"year": 2026},
        "week": {"number": 1},
        "competitions": [
            {
                "status": {"type": {"state": "in"}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "24",
                        "team": {"displayName": "Kansas City Chiefs"},
                    }
                    # away competitor entirely absent this poll - the score
                    # variable for it never gets set, so home_seen/away_seen
                    # is the only thing that can correctly distinguish "no
                    # update" from "update to None".
                ],
            }
        ],
    }
    run = IngestionRun(source="espn")

    result = await _upsert_event(db, event, run)

    assert result is not None and result.id == existing.id
    assert result.home_score == 24, "the side present this poll must update"
    assert result.away_score == 14, (
        "the side absent from this poll's competitor list must keep its "
        "prior DB value, not be nulled out"
    )
