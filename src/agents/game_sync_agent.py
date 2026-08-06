"""CONSTRAINT #3: class name is `GameSyncAgent`.

ESPN -> `games` table upsert. This is the backbone sync (no quota, runs on a
short interval for every sport) that keeps `status` current as
scheduled -> live -> final, which everything else (odds polling scope,
props game_id resolution, the /games API default) depends on.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.providers.espn_api import get_games
from src.data.team_resolution import resolve_team
from src.models.orm import Game
from src.utils.logging import get_logger

log = get_logger(__name__)


def _parse_game_time(raw: str | None) -> datetime | None:
    """ESPN sends `2026-08-02T23:00Z`. Python's fromisoformat (3.12) accepts
    Z as of 3.11, but not the missing-seconds form some ESPN feeds use, so
    normalise both quirks before parsing."""
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            # Missing seconds: "2026-08-02T23:00+00:00" -> add ":00".
            date_part, _, tz_part = text.partition("+")
            if date_part.count(":") == 1:
                text = f"{date_part}:00+{tz_part}"
                return datetime.fromisoformat(text)
        except ValueError:
            pass
        return None


class GameSyncAgent:
    """Upserts ESPN scoreboard events into `games`, keyed on
    (sport, espn_event_id) per the `uq_game_espn` constraint."""

    async def sync_sport(self, db: AsyncSession, sport: str, *, day: date | None = None) -> int:
        parsed_games = await get_games(sport, day=day)
        log.info("game_sync.fetched", sport=sport, count=len(parsed_games))

        upserted = 0
        for g in parsed_games:
            home_team_id = await resolve_team(
                db, sport, g.get("home_team_name"), g.get("home_team_espn_id")
            )
            away_team_id = await resolve_team(
                db, sport, g.get("away_team_name"), g.get("away_team_espn_id")
            )

            values = {
                "sport": sport,
                "espn_event_id": g["espn_event_id"],
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_team_name": g.get("home_team_name"),
                "away_team_name": g.get("away_team_name"),
                "game_time": _parse_game_time(g.get("game_time")),
                "status": g["status"],
                "home_score": g.get("home_score"),
                "away_score": g.get("away_score"),
                "season": g.get("season"),
                "week": g.get("week"),
            }

            stmt = pg_insert(Game).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_game_espn",
                set_={
                    "status": stmt.excluded.status,
                    "game_time": stmt.excluded.game_time,
                    "home_score": stmt.excluded.home_score,
                    "away_score": stmt.excluded.away_score,
                    "home_team_id": stmt.excluded.home_team_id,
                    "away_team_id": stmt.excluded.away_team_id,
                    "updated_at": datetime.utcnow(),
                },
            )
            await db.execute(stmt)
            upserted += 1

        await db.commit()
        log.info("game_sync.upserted", sport=sport, count=upserted)
        return upserted

    async def sync_all(self, db: AsyncSession, sports: list[str]) -> dict[str, int]:
        return {sport: await self.sync_sport(db, sport) for sport in sports}
