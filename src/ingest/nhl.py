"""NHL schedule and scores from the official, unauthenticated NHL API
(api-web.nhle.com) - the primary NHL source, not ESPN's undocumented
scoreboard (see config/settings.py's `espn_sports`, which excludes "nhl"
the same way it excludes "mlb"). No key, no documented rate limit, plain
httpx like theodds.py's/mlb.py's own clients.

`/v1/schedule/{date}` returns a 7-day window (`gameWeek`) starting at that
date, each game already carrying both teams' scores - one call per week,
not one per day, unlike ESPN's per-date scoreboard.

Team resolution uses each side's `abbrev` field directly (e.g. "VGK",
"CAR"), NOT a full team name - the NHL API's own team.name is just the
nickname ("Canadiens", not "Montreal Canadiens"), so it can't be matched
against ESPN's displayName the way MLB Stats API's full names could.
config/team_aliases/nhl.yaml is keyed by the NHL API's own abbreviations
for exactly this reason (see that file's own docstring) - direct alias-key
lookup in resolve_team(), no espn_name fallback needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.games import resolve_game
from src.ingest.identity import resolve_team
from src.ingest.runs import record_run
from src.models.facts import Game
from src.models.governance import IngestionRun
from src.services.elo import update_ratings_after_game

SOURCE = "nhl"

# NHL API's own gameState - verified live 2026-09-04 against a real Final
# game (gameState "OFF") and a real future game (gameState "FUT"). "LIVE"/
# "CRIT" (critical - a close, active game) are documented NHL API states
# inferred from its public state machine, not independently observed
# against a real in-progress game.
_STATUS_MAP = {
    "FUT": "scheduled", "PRE": "scheduled",
    "LIVE": "in_progress", "CRIT": "in_progress",
    "OFF": "final", "FINAL": "final",
}

# NHL API's own gameType codes - 2 (regular season) and 3 (playoffs,
# verified live 2026-09-04 against a real June Stanley Cup Final game) are
# confirmed; 1 (preseason) follows the league's well-known convention but
# was not independently observed against a real preseason game.
_GAME_TYPE_MAP = {1: "PRE", 2: "REG"}


async def sync_schedule(db: AsyncSession, days_ahead: int = 7, start_date: str | None = None) -> int:
    """`start_date` (YYYY-MM-DD) overrides today - used by
    scripts/bootstrap_ratings.py to backfill past weeks. `days_ahead` is
    honored by however many /schedule/{date} calls (each a 7-day window)
    are needed to cover it, not a raw day count passed to the API."""
    if start_date is None:
        start_date = f"{datetime.now(timezone.utc).date():%Y-%m-%d}"

    async with record_run(db, SOURCE) as run:
        cursor = start_date
        weeks_needed = max(1, -(-days_ahead // 7))  # ceil division
        async with httpx.AsyncClient(timeout=20.0) as client:
            for _ in range(weeks_needed):
                response = await client.get(
                    f"{get_settings().nhl_api_base_url}/schedule/{cursor}"
                )
                response.raise_for_status()
                payload = response.json()

                for day in payload.get("gameWeek", []):
                    for game in day.get("games", []):
                        if await _upsert_game(db, game, run):
                            run.rows_written += 1

                cursor = payload.get("nextStartDate")
                if not cursor:
                    break
        await db.commit()
        return run.rows_written


async def _upsert_game(db: AsyncSession, game: dict[str, Any], run: IngestionRun) -> bool:
    game_id = game.get("id")
    if game_id is None:
        return False
    game_id = str(game_id)

    home_abbrev = (game.get("homeTeam") or {}).get("abbrev")
    away_abbrev = (game.get("awayTeam") or {}).get("abbrev")
    if not home_abbrev or not away_abbrev:
        run.detail = f"nhl game {game_id}: missing team abbrev in this poll"[:2000]
        return False

    try:
        home = await resolve_team(db, home_abbrev, sport="nhl")
        away = await resolve_team(db, away_abbrev, sport="nhl")
    except LookupError:
        run.detail = f"nhl game {game_id}: no alias for {home_abbrev!r}/{away_abbrev!r}"[:2000]
        return False

    existing = await db.scalar(select(Game).where(Game.nhl_game_id == game_id))
    is_new = existing is None
    was_final = (not is_new) and existing.status == "final"

    kickoff = _kickoff(game)
    if is_new:
        record = await resolve_game(
            db, home_team_id=home.id, away_team_id=away.id, kickoff=kickoff, nhl_id=game_id
        )
        record.sport = "nhl"
    else:
        record = existing

    season = game.get("season")
    # NHL's season is a single int spanning two years (e.g. 20252026) -
    # store the START year, matching how the rest of this schema treats
    # `season` as one calendar/competitive year, not a literal passthrough.
    record.season = int(str(season)[:4]) if season else record.season
    record.game_type = _GAME_TYPE_MAP.get(game.get("gameType"), "POST")
    if kickoff is not None:
        record.game_time = kickoff
    record.home_team_id, record.away_team_id = home.id, away.id

    state = game.get("gameState")
    record.status = _STATUS_MAP.get(state, "scheduled")

    home_score = (game.get("homeTeam") or {}).get("score")
    away_score = (game.get("awayTeam") or {}).get("score")
    if home_score is not None:
        record.home_score = int(home_score)
    if away_score is not None:
        record.away_score = int(away_score)

    await db.flush()
    if not was_final and record.status == "final":
        await update_ratings_after_game(db, record)
    return True


def _kickoff(game: dict[str, Any]) -> datetime | None:
    """NHL API's startTimeUTC is already UTC ISO8601."""
    date_text = game.get("startTimeUTC")
    if not date_text:
        return None
    return datetime.fromisoformat(date_text.replace("Z", "+00:00"))
