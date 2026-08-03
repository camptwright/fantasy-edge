"""CONSTRAINT #3: class name is `OddsMonitor`.

Polls The Odds API for one sport, writes every observation as an immutable
`OddsSnapshot` row, and compares each (game, market, bookmaker, outcome)
against its last-known value in Redis to detect line movement. A significant
move publishes to `CHANNEL_LINE_MOVEMENT` and schedules a ValueAgent run for
that game via Celery, so a moving line gets re-evaluated without waiting for
the next full poll cycle.

The Celery task is imported lazily inside `_trigger_value_agent`, not at
module level. `src/scheduler/tasks.py` does not exist until Phase 4; a
top-level import would make this module fail to import during the Phase 2
smoke test ("import smoke test for every agent class") months before the
scheduler exists. Deferring the import means Phase 2 is self-contained today
and the wiring activates automatically once Phase 4 lands - no code here
needs to change.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.cache.redis_client import (
    CHANNEL_LINE_MOVEMENT,
    KEY_ODDS_LAST_SEEN,
    get_worker_redis,
)
from src.data.providers.theodds_api import QuotaExhaustedError, get_odds
from src.models.orm import Game, OddsSnapshot
from src.utils.logging import get_logger
from src.utils.odds_math import american_to_implied
from sqlalchemy import select

log = get_logger(__name__)

# A move is "significant" if implied probability shifted by more than this
# many percentage points, or (for spreads/totals) the point moved at all -
# even 0.5 on a total is a meaningful market signal, unlike price noise.
IMPLIED_PROB_MOVE_THRESHOLD = 0.03


class OddsMonitor:
    async def _find_game_id(
        self, db: AsyncSession, sport: str, odds_api_event_id: str, home: str, away: str
    ) -> str | None:
        result = await db.execute(
            select(Game.id).where(
                Game.sport == sport, Game.odds_api_event_id == odds_api_event_id
            )
        )
        row = result.first()
        if row:
            return str(row[0])
        # Fall back to matching on team names + backfill the odds_api id so
        # the next poll hits the fast path above.
        result = await db.execute(
            select(Game.id).where(
                Game.sport == sport,
                Game.home_team_name == home,
                Game.away_team_name == away,
            )
        )
        row = result.first()
        if row:
            await db.execute(
                Game.__table__.update()
                .where(Game.id == row[0])
                .values(odds_api_event_id=odds_api_event_id)
            )
            return str(row[0])
        return None

    async def _trigger_value_agent(self, game_id: str) -> None:
        try:
            from src.scheduler.tasks import run_value_agent_for_game
        except ImportError:
            log.info("odds_monitor.value_agent_not_wired_yet", game_id=game_id)
            return
        run_value_agent_for_game.delay(game_id)

    async def poll_sport(self, db: AsyncSession, sport: str) -> int:
        # A fresh client per call, not the API's shared get_redis() - this
        # method only ever runs inside a Celery task's own asyncio.run()
        # loop, and get_worker_redis() is what stays correct across
        # successive, independent event loops. See redis_client.py's
        # module docstring for the traceback this replaced.
        async with get_worker_redis() as redis:
            try:
                events = await get_odds(redis, sport)
            except QuotaExhaustedError:
                log.warning("odds_monitor.quota_exhausted", sport=sport)
                return 0

            snapshots_written = 0
            moved_games: set[str] = set()

            for event in events:
                odds_api_event_id = event["id"]
                home = event.get("home_team")
                away = event.get("away_team")
                game_id = await self._find_game_id(db, sport, odds_api_event_id, home, away)

                for bookmaker in event.get("bookmakers", []):
                    book_key = bookmaker.get("key", "unknown")
                    for market in bookmaker.get("markets", []):
                        market_key = market.get("key", "unknown")
                        for outcome in market.get("outcomes", []):
                            price = outcome.get("price")
                            if price is None:
                                continue
                            point = outcome.get("point")
                            name = outcome.get("name", "")

                            implied = american_to_implied(price)
                            db.add(
                                OddsSnapshot(
                                    game_id=game_id,
                                    sport=sport,
                                    bookmaker=book_key,
                                    market=market_key,
                                    outcome=name,
                                    price_american=int(price),
                                    price_decimal=None,
                                    point=point,
                                    implied_probability=implied,
                                )
                            )
                            snapshots_written += 1

                            redis_key = KEY_ODDS_LAST_SEEN.format(
                                sport=sport,
                                game_id=game_id or odds_api_event_id,
                                market=market_key,
                                bookmaker=book_key,
                                outcome=name,
                            )
                            previous_raw = await redis.get(redis_key)
                            moved = False
                            if previous_raw:
                                previous = json.loads(previous_raw)
                                prev_implied = previous.get("implied_probability")
                                prev_point = previous.get("point")
                                if prev_implied is not None and abs(
                                    implied - prev_implied
                                ) >= IMPLIED_PROB_MOVE_THRESHOLD:
                                    moved = True
                                if (
                                    point is not None
                                    and prev_point is not None
                                    and point != prev_point
                                ):
                                    moved = True

                            await redis.set(
                                redis_key,
                                json.dumps({"implied_probability": implied, "point": point}),
                                ex=86400,
                            )

                            if moved and game_id:
                                moved_games.add(game_id)
                                await redis.publish(
                                    CHANNEL_LINE_MOVEMENT,
                                    json.dumps(
                                        {
                                            "sport": sport,
                                            "game_id": game_id,
                                            "market": market_key,
                                            "bookmaker": book_key,
                                            "outcome": name,
                                            "implied_probability": implied,
                                            "point": point,
                                        }
                                    ),
                                )

            await db.commit()

            for game_id in moved_games:
                await self._trigger_value_agent(game_id)

            log.info(
                "odds_monitor.polled",
                sport=sport,
                events=len(events),
                snapshots=snapshots_written,
                moved=len(moved_games),
            )
            return snapshots_written

    async def poll_all(self, db: AsyncSession, sports: list[str]) -> dict[str, int]:
        results: dict[str, int] = {}
        for sport in sports:
            results[sport] = await self.poll_sport(db, sport)
        return results
