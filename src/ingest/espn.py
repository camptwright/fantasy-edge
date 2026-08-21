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
            game = await _upsert_event(db, event)
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


async def _upsert_event(db: AsyncSession, event: dict[str, Any]) -> Game | None:
    event_id = str(event.get("id") or "")
    if not event_id:
        return None

    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]

    game = await db.scalar(select(Game).where(Game.espn_event_id == event_id))
    if game is None:
        game = Game(espn_event_id=event_id)
        db.add(game)

    # CONSTRAINT: games.season is NOT NULL. resolve_team() below issues a
    # SELECT (and sometimes a flush of its own) against the same session, and
    # SQLAlchemy autoflushes pending objects before running any query. A
    # freshly created Game added above has season=None until this method
    # assigns it, so that autoflush would try to INSERT a row with a NULL
    # season and crash with NotNullViolationError. Every NOT NULL field must
    # therefore be set on `game` before the competitor-resolution loop below
    # runs any query.
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

    home = away = None
    for competitor in competition.get("competitors", []):
        team_name = (competitor.get("team") or {}).get("displayName")
        if not team_name:
            continue
        resolved = await resolve_team(db, team_name)
        if competitor.get("homeAway") == "home":
            home, home_score = resolved, competitor.get("score")
            game.home_score = int(home_score) if home_score not in (None, "") else None
        else:
            away, away_score = resolved, competitor.get("score")
            game.away_score = int(away_score) if away_score not in (None, "") else None

    if home is None or away is None:
        return None

    game.home_team_id, game.away_team_id = home.id, away.id
    await db.flush()
    return game


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
