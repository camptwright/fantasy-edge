"""NCAAF player identity from ESPN team rosters - the only seeding path
for NCAAF players. Nothing else in this app creates a Player row for this
sport (docs/nfl-modeling.md: "NCAAF has no nflverse equivalent"), and
resolve_player() only matches existing players, it never creates one (two
active players can share a name, so guessing is worse than parking - see
its own docstring). Without this, every Underdog/PrizePicks NCAAF prop
parks as unresolvable forever.

One HTTP request per team - ESPN has no league-wide roster endpoint for
college football (verified live 2026-09-05: /athletes 404s), unlike its
per-sport teams list or MLB Stats API's /sports/{id}/players. ~137
requests for the full FBS, run from whichever NCAAF Team rows already
exist (created by src/ingest/espn.py's own sync, which already has each
team's espn_id) rather than re-reading config/team_aliases/ncaaf.yaml
directly. A seeding script, run occasionally like scripts/ingest_history.py
and NFL's own ingest_players(), not a live poller.

current_team_id is deliberately left unset, matching src/ingest/players.py
(NFL)'s own existing precedent.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.runs import record_run
from src.models.identity import Player, PlayerExternalId, Team

SOURCE = "espn_ncaaf"


async def ingest_players(db: AsyncSession) -> int:
    teams = (await db.execute(select(Team).where(Team.sport == "ncaaf"))).scalars().all()

    async with record_run(db, SOURCE) as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for team in teams:
                response = await client.get(
                    f"{get_settings().espn_base_urls['ncaaf']}/teams/{team.espn_id}/roster"
                )
                if response.status_code != 200:
                    # One team's roster being temporarily unavailable
                    # shouldn't abort the other 136 - recorded via run.detail
                    # rather than silently ignored.
                    run.detail = f"team {team.espn_id} ({team.name}): HTTP {response.status_code}"[:2000]
                    continue
                payload = response.json()
                for group in payload.get("athletes") or []:
                    for athlete in group.get("items") or []:
                        if await _upsert_player(db, athlete):
                            run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _upsert_player(db: AsyncSession, athlete: dict[str, Any]) -> bool:
    external_id = str(athlete.get("id") or "")
    full_name = athlete.get("fullName")
    if not external_id or not full_name:
        return False

    existing = await db.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.source == SOURCE, PlayerExternalId.external_id == external_id
        )
    )
    if existing is not None:
        return False

    position = (athlete.get("position") or {}).get("abbreviation")
    player = Player(sport="ncaaf", full_name=full_name, position=position)
    db.add(player)
    await db.flush()
    db.add(PlayerExternalId(player_id=player.id, source=SOURCE, external_id=external_id))
    return True
