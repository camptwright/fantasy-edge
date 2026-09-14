"""Live NFL schedule, scores, and published game odds from ESPN.

ESPN is the free backbone: no key, no documented quota. It supplies fixtures
and scores, plus competition odds used as a secondary market source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.games import resolve_game
from src.ingest.identity import resolve_team
from src.ingest.lines import record_team_line
from src.ingest.runs import record_run
from src.models.facts import Game
from src.models.governance import IngestionRun
from src.services.elo import update_ratings_after_game
from src.services.team_rating_repair import lock_sport, repair_changed_score

SOURCE = "espn"

# ESPN's season.type: verified live 2026-08-22 against the real scoreboard
# endpoint - 1/2/3 map to the "preseason"/"regular-season"/"post-season"
# slugs the response itself carries.
_PRESEASON = 1
_REGULAR_SEASON = 2
_POSTSEASON = 3

# ESPN's postseason week.number: verified live 2026-08-22 by requesting the
# real 2024-season playoff dates and reading season/week back off each
# round (Wild Card weekend -> 1, Divisional -> 2, Conference Championship
# -> 3, Pro Bowl -> 4, Super Bowl -> 5). nflverse has no Pro Bowl row, so
# week 4 (or any other unrecognised number) is deliberately left unmapped
# rather than guessed.
_ESPN_POSTSEASON_GAME_TYPE = {1: "WC", 2: "DIV", 3: "CON", 5: "SB"}
_ESPN_POSTSEASON_WEEK_OFFSET = {1: 0, 2: 1, 3: 2, 5: 3}

# nflverse's own postseason week NUMBERS moved when the season expanded to
# 17 regular-season games in 2021 (verified live against the real DB:
# `SELECT DISTINCT season, week, game_type FROM games WHERE game_type IN
# ('WC','DIV','CON','SB')` - seasons >=2021 use weeks 19-22 for
# WC/DIV/CON/SB; seasons <2021 use weeks 18-21). The base below picks
# whichever epoch the event's own season falls in rather than hardcoding
# one of them.
_POSTSEASON_WEEK_BASE_MODERN = 19
_POSTSEASON_WEEK_BASE_LEGACY = 18
_SEVENTEEN_GAME_SEASON_START = 2021


# NCAAF's `groups=80` scope the scoreboard to FBS - verified live 2026-08-29
# against a real November Saturday (45 games, zero non-FBS opponents).
# Without it, ESPN also returns FCS-only matchups this app doesn't model.
_ESPN_SCOREBOARD_PARAMS = {"nfl": {}, "ncaaf": {"groups": "80"}}


async def sync_scoreboard(
    db: AsyncSession, sport: str = "nfl", days_ahead: int = 7, dates: str | None = None
) -> int:
    """`dates` overrides the default today-forward window with an explicit
    ESPN `dates` value (a single `YYYYMMDD`, or a `YYYYMMDD-YYYYMMDD` range)
    - used by scripts/bootstrap_ratings.py to backfill past seasons through
    the same insert-on-change path live sync uses, rather than a second
    parser. ESPN's own range support is undocumented and unreliable beyond
    roughly a week, so the bootstrap script passes single dates in a loop
    rather than one season-wide range."""
    settings = get_settings()
    if dates is None:
        today = datetime.now(timezone.utc).date()
        dates = f"{today - timedelta(days=1):%Y%m%d}-{today + timedelta(days=days_ahead):%Y%m%d}"
    params = {"dates": dates, "limit": "1000", **_ESPN_SCOREBOARD_PARAMS.get(sport, {})}

    async with record_run(db, f"{SOURCE}_{sport}") as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{settings.espn_base_urls[sport]}/scoreboard", params=params
            )
            response.raise_for_status()
            payload = response.json()

        for event in payload.get("events", []):
            game = await _upsert_event(db, event, run, sport)
            if game is None:
                continue
            for entry in _odds_rows(event):
                if await record_team_line(
                    db,
                    game_id=game.id,
                    source=SOURCE,
                    line_type="live",
                    **entry,
                ):
                    run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _upsert_event(
    db: AsyncSession, event: dict[str, Any], run: IngestionRun, sport: str = "nfl"
) -> Game | None:
    """Create or update the Game for one ESPN event.

    Team resolution is deliberately run BEFORE a brand-new Game is ever
    constructed or added to the session. `games.season` is NOT NULL, and
    once a pending Game satisfies every NOT NULL constraint, any query
    issued on this session (e.g. resolve_team()'s own SELECT for the very
    next competitor, or the next event's lookup) autoflushes the whole unit
    of work - which would silently INSERT a half-built Game (valid team IDs
    still unknown) before we've even learned whether resolution will
    succeed. Resolving first means a malformed event never gets a pending
    row in the session in the first place, so there is nothing to discard
    if it turns out incomplete - this is a stronger guarantee than adding
    the Game early and expunging it after the fact, which would already be
    too late if an intervening query had autoflushed it.

    If the Game already exists (a prior successful sync gave it valid team
    IDs) and THIS poll's competitor data is incomplete, the existing valid
    team IDs are kept untouched; only the team assignment is skipped, while
    schedule/status/score fields this poll does legitimately know are still
    applied. Either way, a failure is recorded on `run.detail` so a
    persistently malformed event doesn't go unnoticed.

    A brand-new event (no existing row for this espn_event_id) is resolved
    through resolve_game() rather than unconditionally constructed, so a
    Game nflverse already seeded for this exact fixture (keyed only on
    nflverse_game_id, matched here by team pair + kickoff window) gets
    espn_event_id backfilled onto it instead of gaining a duplicate row -
    without which closing (nflverse) and live (ESPN) lines for the same
    real game could never be joined.
    """
    event_id = str(event.get("id") or "")
    if not event_id:
        return None

    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]

    await lock_sport(db, sport)
    game = await db.scalar(select(Game).where(Game.espn_event_id == event_id))
    is_new = game is None
    # Elo must update exactly once per game, the moment it first becomes
    # final - never on a later poll of an already-final game (see
    # update_ratings_after_game's own docstring on this being the caller's
    # responsibility).
    was_final = (not is_new) and game.status == "final"
    old_score = (game.home_score, game.away_score) if was_final else None

    home = away = None
    home_score = away_score = None
    # Tracks whether a competitor entry for that side was present in THIS
    # poll at all - independent of whether it carried a resolvable team name
    # or a numeric score. A side that's absent from `competitors` entirely
    # (e.g. a transient ESPN payload glitch) must leave that side's existing
    # DB score untouched; a side that IS present but pre-kickoff and
    # scoreless legitimately means score=None and should still apply.
    home_seen = away_seen = False
    for competitor in competition.get("competitors", []):
        is_home = competitor.get("homeAway") == "home"
        if is_home:
            home_seen = True
        else:
            away_seen = True
        team_name = (competitor.get("team") or {}).get("displayName")
        if not team_name:
            continue
        try:
            resolved = await resolve_team(db, team_name, sport=sport)
        except LookupError:
            # NCAAF's `groups=80` scope includes any game with at least one
            # FBS participant, not FBS-vs-FBS only (verified live 2026-08-29
            # ingesting a real slate: Bethune-Cookman, an FCS team, appeared
            # as an opponent's buy-game). An opponent outside our alias file
            # must be treated the same as "no team_name" below - park this
            # side, don't crash the whole poll over one unmodeled team.
            continue
        if is_home:
            home, home_score = resolved, competitor.get("score")
        else:
            away, away_score = resolved, competitor.get("score")

    if home is None or away is None:
        run.detail = (
            f"espn event {event_id}: incomplete competitor data this poll "
            f"(home={'ok' if home else 'missing'}, away={'ok' if away else 'missing'})"
        )[:2000]
        if is_new:
            # Nothing was ever added to the session for this event - there
            # is no partial row to discard.
            return None
        # Existing game: keep its valid team IDs, but still record whatever
        # this poll legitimately knows - schedule/status and scores don't
        # depend on team resolution succeeding. Per-side score updates are
        # further gated on home_seen/away_seen so a side missing from this
        # poll's competitor list entirely keeps its existing DB score
        # rather than being nulled out.
        _apply_schedule_fields(game, event, competition, sport)
        _apply_scores(game, home_score, away_score, home_seen, away_seen)
        await db.flush()
        if not was_final and game.status == "final":
            await update_ratings_after_game(db, game)
        elif was_final:
            await repair_changed_score(db, game, old_score)
        return game

    if is_new:
        game = await resolve_game(
            db,
            home_team_id=home.id,
            away_team_id=away.id,
            kickoff=_kickoff_from_event(event),
            espn_id=event_id,
        )
        game.sport = sport

    _apply_schedule_fields(game, event, competition, sport)
    _apply_scores(game, home_score, away_score, home_seen, away_seen)
    game.home_team_id, game.away_team_id = home.id, away.id
    await db.flush()
    if not was_final and game.status == "final":
        await update_ratings_after_game(db, game)
    elif was_final:
        await repair_changed_score(db, game, old_score)
    return game


def _kickoff_from_event(event: dict[str, Any]) -> datetime | None:
    """ESPN's `event.date` is already UTC (unlike nflverse's Eastern-local
    `gametime` - see src/ingest/nflverse.py's `_kickoff()`). Shared by
    `_upsert_event`'s resolve_game() call, which needs kickoff BEFORE a
    Game exists to run its kickoff-window match, and `_apply_schedule_fields`,
    which needs the same value once the Game does exist - one parser for
    both keeps them from drifting apart."""
    date_text = event.get("date")
    if not date_text:
        return None
    return datetime.fromisoformat(date_text.replace("Z", "+00:00"))


def _game_type_and_week(event: dict[str, Any], sport: str = "nfl") -> tuple[str | None, int | None]:
    """Map ESPN's season.type + week.number to a game_type/week pair.

    NFL: aligned to nflverse's own vocabulary (REG/WC/DIV/CON/SB) and week
    numbering, per the detailed remapping below - required so nflverse's
    historically-seeded rows and ESPN's live-synced rows for the same game
    join on identical values.

    NCAAF has no nflverse equivalent to align to (nflreadpy doesn't cover
    college football - see docs/nfl-modeling.md), so its postseason is left
    as ESPN's own raw week.number under game_type "POST" rather than
    invented WC/DIV/CON/SB rounds that don't correspond to how bowl season
    actually works (dozens of bowls plus a multi-round CFP, not four fixed
    rounds).

    nflverse's live DB has no "PRE" game_type at all (it doesn't carry
    preseason games), so introducing "PRE" here for ESPN preseason events
    is a new value, not a collision with an existing one.
    """
    season = event.get("season") or {}
    season_type = season.get("type")
    week_number = (event.get("week") or {}).get("number")

    if season_type == _PRESEASON:
        return "PRE", week_number
    if season_type == _REGULAR_SEASON:
        return "REG", week_number
    if season_type == _POSTSEASON:
        if sport != "nfl":
            return "POST", week_number
        # Week 4 (or any other postseason week.number ESPN doesn't document
        # as a real competitive round, i.e. the Pro Bowl) is deliberately
        # left unmapped rather than guessed - and in practice its
        # "AFC"/"NFC" team names don't resolve through resolve_team()
        # anyway.
        game_type = _ESPN_POSTSEASON_GAME_TYPE.get(week_number)
        if game_type is None:
            return None, None
        season_year = season.get("year")
        base_week = (
            _POSTSEASON_WEEK_BASE_MODERN
            if season_year is not None and int(season_year) >= _SEVENTEEN_GAME_SEASON_START
            else _POSTSEASON_WEEK_BASE_LEGACY
        )
        return game_type, base_week + _ESPN_POSTSEASON_WEEK_OFFSET[week_number]
    return None, week_number


def _apply_schedule_fields(
    game: Game, event: dict[str, Any], competition: dict[str, Any], sport: str = "nfl"
) -> None:
    """Season/week/game_type/kickoff/status - shared by the happy path and
    the existing-game-but-this-poll-is-incomplete path so both apply the
    same parsing rather than duplicating it."""
    season = (event.get("season") or {}).get("year")
    game.season = int(season) if season else game.season

    game_type, normalized_week = _game_type_and_week(event, sport)
    if normalized_week is not None:
        game.week = int(normalized_week)
    if game_type is not None:
        game.game_type = game_type

    kickoff = _kickoff_from_event(event)
    if kickoff is not None:
        game.game_time = kickoff

    state = ((competition.get("status") or {}).get("type") or {}).get("state")
    game.status = {"pre": "scheduled", "in": "in_progress", "post": "final"}.get(
        state, "scheduled"
    )


def _apply_scores(
    game: Game,
    home_score: Any,
    away_score: Any,
    home_seen: bool,
    away_seen: bool,
) -> None:
    """Only touch a side's score if that side actually had a competitor
    entry in this poll. A side missing from this poll entirely must leave
    the existing DB value alone rather than being coerced to None."""
    if home_seen:
        game.home_score = int(home_score) if home_score not in (None, "") else None
    if away_seen:
        game.away_score = int(away_score) if away_score not in (None, "") else None


def _odds_rows(event: dict[str, Any]) -> list[dict[str, Any]]:
    """ESPN publishes one consensus odds block per competition, when available.

    SIGN: ESPN's `spread` is already the HOME team's line in sportsbook
    convention - negative when the home team is favoured. Verified live
    2026-08-20 on LV @ HOU: details 'LV -1.5' (LV is the away team),
    spread = 1.5, homeTeamOdds.favorite = False. So the home row takes
    `spread` unchanged and the away row is its negation.

    Note this is the exact mirror of nflverse, which publishes a POSITIVE
    spread_line when the home team is favoured. Both ingesters normalise to
    the storage convention documented in src/models/facts.py.
    """
    competitions = event.get("competitions") or []
    if not competitions:
        return []
    odds_blocks = competitions[0].get("odds") or []
    if not odds_blocks:
        return []
    block = odds_blocks[0]

    rows: list[dict[str, Any]] = []
    spread = block.get("spread")
    if spread is not None:
        rows.append({"market": "spread", "side": "home", "line": float(spread),
                     "price_american": None})
        rows.append({"market": "spread", "side": "away", "line": -float(spread),
                     "price_american": None})
    total = block.get("overUnder")
    if total is not None:
        rows.append({"market": "total", "side": "over", "line": float(total),
                     "price_american": None})
        rows.append({"market": "total", "side": "under", "line": float(total),
                     "price_american": None})
    return rows
