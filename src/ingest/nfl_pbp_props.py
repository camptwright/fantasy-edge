"""Offline NFL play-by-play outcomes for explicitly supported long-yardage props.

The ordinary nflverse player-stat feed deliberately remains the default
historical path. It has no longest-rush or longest-reception fields, so this
optional backfill reads the official nflverse play-by-play release only when a
maintainer requests it. It is never imported by the serving image or scheduler.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingest.nflverse import _nflreadpy, _records
from src.ingest.runs import record_run
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player

SOURCE = "nflverse:pbp_props"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _one(value: Any) -> bool:
    number = _number(value)
    return number == 1


def longest_rows(records: list[dict[str, Any]]) -> dict[tuple[str, str, str], float]:
    """Return each player's observed maximum from valid individual plays.

    We require nflverse's explicit play classification and player identifier.
    Team plays, null players, malformed values, and non-completions are not
    evidence of an individual outcome.
    """
    values: dict[tuple[str, str, str], float] = {}
    for row in records:
        game_id = str(row.get("game_id") or "")
        yards = _number(row.get("yards_gained"))
        if not game_id or yards is None:
            continue
        if _one(row.get("complete_pass")):
            player_id = str(row.get("receiver_player_id") or "")
            if player_id:
                key = (game_id, player_id, "longest_reception")
                values[key] = max(values.get(key, yards), yards)
        if _one(row.get("rush_attempt")):
            player_id = str(row.get("rusher_player_id") or "")
            if player_id:
                key = (game_id, player_id, "longest_rush")
                values[key] = max(values.get(key, yards), yards)
    return values


async def ingest_longest_props(db: AsyncSession, seasons: list[int]) -> int:
    """Store maxima for requested seasons; repeat runs preserve prior facts."""
    records = _records(_nflreadpy().load_pbp(seasons))
    observed = longest_rows(records)
    game_ids = {game for game, _, _ in observed}
    player_ids = {player for _, player, _ in observed}
    games = {g.nflverse_game_id: g.id for g in (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.nflverse_game_id.in_(game_ids)))).all()}
    players = {p.gsis_id: p.id for p in (await db.scalars(select(Player).where(
        Player.sport == "nfl", Player.gsis_id.in_(player_ids)))).all()}
    rows = [{"game_id": games[game], "player_id": players[player], "stat_type": stat, "value": value}
            for (game, player, stat), value in observed.items() if game in games and player in players]
    written = 0
    async with record_run(db, SOURCE) as run:
        for start in range(0, len(rows), 500):
            result = await db.execute(insert(PlayerGameStat).values(rows[start:start + 500]).on_conflict_do_nothing(
                index_elements=["player_id", "game_id", "stat_type"]).returning(PlayerGameStat.id))
            written += len(result.all())
        run.rows_written = written
        run.detail = f"{len(rows)} mapped longest-play facts from nflverse play-by-play"
        await db.commit()
    return written
