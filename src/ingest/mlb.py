"""MLB schedule and scores from the official, unauthenticated MLB Stats API
(statsapi.mlb.com) - the primary MLB source, not ESPN's undocumented
scoreboard (see config/settings.py's `espn_sports`, which deliberately
excludes "mlb"). The free-source research is explicit that this is the
most stable, comprehensive free source available for any sport; unlike
Pinnacle/Bovada it needs no TLS impersonation or archiving - no key, no
documented rate limit, plain httpx like theodds.py's own client.

Team names in this API's response are identical strings to ESPN's own
displayName (cross-checked live 2026-09-04 across a real schedule
response covering 20 different teams), so resolve_team() resolves both
through the same config/team_aliases/mlb.yaml file without any MLB-specific
name matching.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.games import resolve_game
from src.ingest.identity import resolve_team
from src.ingest.runs import record_run
from src.models.facts import Game
from src.models.governance import IngestionRun
from src.services.elo import update_ratings_after_game
from src.services.team_rating_repair import lock_sport, repair_changed_score

SOURCE = "mlb"
# Verified live 2026-09-04 via /api/v1/schedule?sportId=1.
SPORT_ID = 1

# MLB Stats API's own abstractGameState - verified live against both a real
# Final game and a real future Preview game 2026-09-04. "Live" is inferred
# from MLB's documented state machine (Preview -> Live -> Final), not
# independently observed against a real in-progress game.
_STATUS_MAP = {"Preview": "scheduled", "Live": "in_progress", "Final": "final"}

# MLB Stats API's own gameType codes. Only "S" (spring training) and "R"
# (regular season) are mapped explicitly - verified live 2026-09-04.
# Everything else (postseason: wild card/division/championship/World
# Series) collapses to "POST" rather than invented round codes, the same
# choice espn.py already makes for NCAAF's bowl season (no fixed four-round
# structure to name).
_GAME_TYPE_MAP = {"S": "PRE", "R": "REG"}


async def sync_schedule(db: AsyncSession, days_ahead: int = 7, start_date: str | None = None, end_date: str | None = None) -> int:
    """`start_date`/`end_date` (YYYY-MM-DD) override the default
    today-forward window - used by scripts/bootstrap_ratings.py to backfill
    past seasons through the same insert-on-change path live sync uses."""
    live_poll = start_date is None or end_date is None
    if live_poll:
        today = datetime.now(timezone.utc).date()
        start_date = f"{today - timedelta(days=3):%Y-%m-%d}"
        end_date = f"{today + timedelta(days=days_ahead):%Y-%m-%d}"

    async with record_run(db, SOURCE) as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{get_settings().mlb_stats_api_base_url}/schedule",
                params={"sportId": SPORT_ID, "startDate": start_date, "endDate": end_date},
            )
            response.raise_for_status()
            payload = response.json()

            # Reconcile unfinished games even after they leave the normal
            # window (suspensions/postponements included). Unknown kickoff
            # fixtures remain eligible for this identity-based lookup.
            if live_poll:
                overdue = (await db.scalars(select(Game.mlb_game_pk).where(
                    Game.sport == 'mlb', Game.mlb_game_pk.isnot(None),
                    Game.status.in_(['scheduled', 'in_progress']),
                    or_(Game.game_time.is_(None), Game.game_time < datetime.now(timezone.utc)))
                    .order_by(Game.game_time.asc().nulls_last(), Game.id).limit(100))).all()
                if overdue:
                    extra = await client.get(f'{get_settings().mlb_stats_api_base_url}/schedule',
                                             params={'sportId': SPORT_ID, 'gamePks': ','.join(overdue)})
                    extra.raise_for_status()
                    payload.setdefault('dates', []).extend(extra.json().get('dates', []))

        seen = set()
        for date_block in payload.get("dates", []):
            for game in date_block.get("games", []):
                if game.get('gamePk') in seen:
                    continue
                seen.add(game.get('gamePk'))
                if await _upsert_game(db, game, run):
                    run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _upsert_game(db: AsyncSession, game: dict[str, Any], run: IngestionRun) -> bool:
    game_pk = game.get("gamePk")
    if game_pk is None:
        return False
    game_pk = str(game_pk)

    teams = game.get("teams") or {}
    home_name = ((teams.get("home") or {}).get("team") or {}).get("name")
    away_name = ((teams.get("away") or {}).get("team") or {}).get("name")
    if not home_name or not away_name:
        run.detail = f"mlb gamePk {game_pk}: missing team name in this poll"[:2000]
        return False

    try:
        home = await resolve_team(db, home_name, sport="mlb")
        away = await resolve_team(db, away_name, sport="mlb")
    except LookupError:
        run.detail = f"mlb gamePk {game_pk}: no alias for {home_name!r}/{away_name!r}"[:2000]
        return False

    await lock_sport(db, "mlb")
    existing = await db.scalar(select(Game).where(Game.mlb_game_pk == game_pk))
    is_new = existing is None
    was_final = (not is_new) and existing.status == "final"
    old_score = (existing.home_score, existing.away_score) if was_final else None

    kickoff = _kickoff(game)
    if is_new:
        record = await resolve_game(
            db, home_team_id=home.id, away_team_id=away.id, kickoff=kickoff, mlb_id=game_pk
        )
        record.sport = "mlb"
    else:
        record = existing

    season = game.get("season")
    record.season = int(season) if season else record.season
    record.game_type = _GAME_TYPE_MAP.get(game.get("gameType"), "POST")
    if kickoff is not None:
        record.game_time = kickoff
    record.home_team_id, record.away_team_id = home.id, away.id

    state = (game.get("status") or {}).get("abstractGameState")
    record.status = _STATUS_MAP.get(state, "scheduled")
    # MLB includes cancelled games in abstractGameState=Final. They are not
    # played outcomes and must never enter ratings, grading or result retries.
    status_detail = game.get('status') or {}
    if status_detail.get('codedGameState') == 'C' or status_detail.get('detailedState') == 'Cancelled':
        record.status = 'cancelled'

    home_score = (teams.get("home") or {}).get("score")
    away_score = (teams.get("away") or {}).get("score")
    if home_score is not None:
        record.home_score = int(home_score)
    if away_score is not None:
        record.away_score = int(away_score)

    await db.flush()
    if not was_final and record.status == "final":
        await update_ratings_after_game(db, record)
    elif was_final:
        await repair_changed_score(db, record, old_score)
    return True


def _kickoff(game: dict[str, Any]) -> datetime | None:
    """MLB Stats API's gameDate is already UTC ISO8601."""
    date_text = game.get("gameDate")
    if not date_text:
        return None
    return datetime.fromisoformat(date_text.replace("Z", "+00:00"))
