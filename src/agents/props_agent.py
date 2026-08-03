"""CONSTRAINT #3: class name must be exactly `PropsAgent`, matching
`from src.agents.props_agent import PropsAgent`.

Pulls Underdog Fantasy prop lines (constraint #5 - the only allowed props
source), normalises player/stat names at ingest (constraint #8), and inserts
with a Postgres-side dedup guard (constraint #6/#7).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.providers.underdog_api import get_over_under_lines, raw_lines_to_props
from src.models.orm import Game, Player, PlayerPropLine
from src.utils.logging import get_logger
from src.utils.normalize import normalize_player_name, normalize_stat_type

log = get_logger(__name__)


class PropsAgent:
    """Ingests Underdog prop lines into `player_prop_lines`."""

    source = "underdog"

    async def fetch_raw(self) -> list[dict[str, Any]]:
        payload = await get_over_under_lines()
        return raw_lines_to_props(payload)

    async def _resolve_player(
        self, db: AsyncSession, sport: str, normalized_name: str
    ) -> tuple[str | None, str | None]:
        """Returns (player_id, team_id). Underdog's payload has no `teams`
        array (see underdog_api docstring), so team - and therefore game -
        resolution can only happen through a player we already know about
        from ESPN sync, not from anything Underdog tells us directly."""
        result = await db.execute(
            select(Player.id, Player.team_id).where(
                Player.sport == sport, Player.normalized_name == normalized_name
            )
        )
        row = result.first()
        return (str(row[0]), str(row[1]) if row[1] else None) if row else (None, None)

    async def _resolve_game_id(
        self, db: AsyncSession, sport: str, team_id: str | None
    ) -> str | None:
        """Best-effort match to the player's next scheduled/live game."""
        if not team_id:
            return None
        result = await db.execute(
            select(Game.id)
            .where(
                Game.sport == sport,
                Game.status.in_(("scheduled", "live")),
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
            )
            .order_by(Game.game_time.asc().nulls_last())
            .limit(1)
        )
        row = result.first()
        return str(row[0]) if row else None

    async def ingest(self, db: AsyncSession) -> int:
        """Fetch, normalise, and insert. Returns rows actually inserted
        (excludes rows that hit the dedup backstop)."""
        raw_rows = await self.fetch_raw()
        log.info("props_agent.fetched", count=len(raw_rows), source=self.source)

        inserted = 0
        for raw in raw_rows:
            normalized_name = normalize_player_name(raw["player_name"])
            stat_type = normalize_stat_type(raw["raw_stat_type"])
            if not normalized_name or not stat_type:
                continue

            player_id, team_id = await self._resolve_player(db, raw["sport"], normalized_name)
            game_id = await self._resolve_game_id(db, raw["sport"], team_id)

            # CONSTRAINT #6: dedup in Postgres, not Redis. ON CONFLICT against
            # uq_prop_daily (player_name, stat_type, source, line, date) is
            # the DB-enforced equivalent of "INSERT ... WHERE NOT EXISTS" -
            # same guarantee, no race window between the check and the insert.
            #
            # uq_prop_daily is a unique INDEX, not a named constraint - it has
            # to be, since one of its keys is an expression
            # (constraint #13, IMMUTABLE date pinning) and Postgres does not
            # support expression-based UNIQUE table constraints. Postgres's
            # `ON CONFLICT ON CONSTRAINT` clause only resolves against
            # pg_constraint, so it 404s on an index-only unique with
            # "constraint ... does not exist" even though the index is real
            # and unique. Targeting the same columns/expression via
            # `index_elements` instead makes Postgres match the index
            # directly, which is what ON CONFLICT actually needs.
            stmt = (
                pg_insert(PlayerPropLine)
                .values(
                    sport=raw["sport"],
                    source=self.source,
                    player_name=raw["player_name"],
                    normalized_name=normalized_name,
                    player_id=player_id,
                    game_id=game_id,
                    team_name=raw.get("team_name"),
                    stat_type=stat_type,
                    line=raw["line"],
                    over_price_american=raw.get("over_price_american"),
                    under_price_american=raw.get("under_price_american"),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        PlayerPropLine.player_name,
                        PlayerPropLine.stat_type,
                        PlayerPropLine.source,
                        PlayerPropLine.line,
                        text("((captured_at AT TIME ZONE 'UTC')::date)"),
                    ]
                )
            )
            result = await db.execute(stmt)
            inserted += result.rowcount or 0

        await db.commit()
        log.info("props_agent.ingested", inserted=inserted, fetched=len(raw_rows))
        return inserted
