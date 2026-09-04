"""MLB player identity from the official MLB Stats API - the only seeding
path for MLB players. Nothing else in this app creates a Player row for
this sport, and resolve_player() only matches existing players, it never
creates one (two active players can share a name, so guessing is worse
than parking - see its own docstring). Without this, every Underdog/
PrizePicks MLB prop parks as unresolvable forever, the same gap NCAAF had
before src/ingest/ncaaf_players.py.

One request for the whole league (verified live 2026-09-05: /sports/1/
players?season=<year> returns ~1,470 active MLB players in one call) -
unlike NCAAF, MLB Stats API has a real league-wide roster endpoint, no
per-team looping needed.

current_team_id is deliberately left unset, matching src/ingest/players.py
(NFL)'s own existing precedent - that field is never populated by player
seeding there either; MLB's own team id numbering doesn't match this app's
Team.espn_id anyway, and no current feature needs it set.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.runs import record_run
from src.models.identity import Player, PlayerExternalId

SOURCE = "mlb_stats_api"
SPORT_ID = 1


async def ingest_players(db: AsyncSession, season: int | None = None) -> int:
    if season is None:
        season = datetime.now(timezone.utc).year

    async with record_run(db, SOURCE) as run:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{get_settings().mlb_stats_api_base_url}/sports/{SPORT_ID}/players",
                params={"season": season},
            )
            response.raise_for_status()
            payload = response.json()

        for person in payload.get("people") or []:
            if await _upsert_player(db, person):
                run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _upsert_player(db: AsyncSession, person: dict[str, Any]) -> bool:
    external_id = str(person.get("id") or "")
    full_name = person.get("fullName")
    if not external_id or not full_name:
        return False

    existing = await db.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.source == SOURCE, PlayerExternalId.external_id == external_id
        )
    )
    if existing is not None:
        return False

    position = (person.get("primaryPosition") or {}).get("abbreviation")
    player = Player(sport="mlb", full_name=full_name, position=position)
    db.add(player)
    await db.flush()
    db.add(PlayerExternalId(player_id=player.id, source=SOURCE, external_id=external_id))
    return True
