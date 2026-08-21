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
from src.ingest.identity import resolve_team
from src.ingest.lines import record_team_line
from src.ingest.runs import record_run
from src.models.facts import Game
from src.models.governance import IngestionRun

SOURCE = "espn"


async def sync_scoreboard(db: AsyncSession, days_ahead: int = 7) -> int:
    settings = get_settings()
    today = datetime.now(timezone.utc).date()
    window = f"{today:%Y%m%d}-{today + timedelta(days=days_ahead):%Y%m%d}"

    async with record_run(db, SOURCE) as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{settings.espn_base_url}/scoreboard", params={"dates": window}
            )
            response.raise_for_status()
            payload = response.json()

        for event in payload.get("events", []):
            game = await _upsert_event(db, event, run)
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
    db: AsyncSession, event: dict[str, Any], run: IngestionRun
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
    """
    event_id = str(event.get("id") or "")
    if not event_id:
        return None

    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]

    game = await db.scalar(select(Game).where(Game.espn_event_id == event_id))
    is_new = game is None

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
        resolved = await resolve_team(db, team_name)
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
        _apply_schedule_fields(game, event, competition)
        _apply_scores(game, home_score, away_score, home_seen, away_seen)
        await db.flush()
        return game

    if is_new:
        game = Game(espn_event_id=event_id)
        db.add(game)

    _apply_schedule_fields(game, event, competition)
    _apply_scores(game, home_score, away_score, home_seen, away_seen)
    game.home_team_id, game.away_team_id = home.id, away.id
    await db.flush()
    return game


def _apply_schedule_fields(
    game: Game, event: dict[str, Any], competition: dict[str, Any]
) -> None:
    """Season/week/kickoff/status - shared by the happy path and the
    existing-game-but-this-poll-is-incomplete path so both apply the same
    parsing rather than duplicating it."""
    season = (event.get("season") or {}).get("year")
    game.season = int(season) if season else game.season
    week = (event.get("week") or {}).get("number")
    game.week = int(week) if week else game.week

    date_text = event.get("date")
    if date_text:
        game.game_time = datetime.fromisoformat(date_text.replace("Z", "+00:00"))

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
