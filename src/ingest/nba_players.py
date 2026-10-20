"""NBA player identity and current team from ESPN team rosters.

Box scores (src/ingest/result_identities.py) only create a Player once he
has played, so rookies and new signings had no row and every one of their
props parked as unresolvable. One request per team (30), flat `athletes`
list (verified live 2026-10-20 for the 2026-27 season). Unlike NCAAF/NFL
this sets current_team_id: NBA players change teams mid-season, and
theodds_props.select_player rejects a prop whose game does not involve a
recorded current team, so a current roster team is the safer binding.
Players missing from every roster (free agents, waived) keep their old row
and their team is cleared.
"""

from __future__ import annotations

from sqlalchemy import select

import httpx

from config.settings import get_settings
from src.ingest.runs import record_run
from src.models.identity import Player, PlayerExternalId, Team

SOURCE = "espn_nba"


def roster(payload: dict) -> list[tuple[str, str, str | None]]:
    """[(external id, full name, position abbreviation)] from one team's roster payload."""
    out = []
    for athlete in payload.get("athletes") or []:
        external = str(athlete.get("id") or "")
        name = athlete.get("fullName") or athlete.get("displayName")
        if external.isdigit() and isinstance(name, str) and 0 < len(name.strip()) <= 128:
            out.append((external, name.strip(), (athlete.get("position") or {}).get("abbreviation")))
    return out


async def sync_nba_players(db, *, fetch=None) -> dict:
    teams = (await db.scalars(select(Team).where(Team.sport == "nba", Team.espn_id.is_not(None)))).all()
    base = get_settings().espn_base_urls["nba"]
    seen, created, moved, failed = {}, 0, 0, []
    async with record_run(db, "espn_nba_rosters") as run:
        async with httpx.AsyncClient(timeout=20) as client:
            for team in teams:
                try:
                    if fetch:
                        payload = await fetch(team)
                    else:
                        response = await client.get(f"{base}/teams/{team.espn_id}/roster")
                        response.raise_for_status()
                        payload = response.json()
                except (httpx.HTTPError, ValueError):
                    failed.append(team.espn_id)
                    continue
                for external, name, position in roster(payload):
                    seen[external] = (name, position, team.id)
        # Clearing teams needs every roster; a partial pull only adds and moves.
        complete = not failed and len(teams) == 30
        links = {e.external_id: e.player_id for e in (await db.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == SOURCE))).all()}
        players = {p.id: p for p in (await db.scalars(select(Player).where(Player.sport == "nba"))).all()}
        for external, (name, position, team_id) in sorted(seen.items()):
            player = players.get(links.get(external))
            if player is None:
                player = Player(sport="nba", full_name=name, position=position, current_team_id=team_id)
                db.add(player)
                await db.flush()
                db.add(PlayerExternalId(player_id=player.id, source=SOURCE, external_id=external))
                created += 1
                continue
            if player.current_team_id != team_id:
                player.current_team_id = team_id
                moved += 1
            if position and player.position != position:
                player.position = position
        cleared = 0
        if complete:
            rostered = {links.get(e) for e in seen}
            for pid, player in players.items():
                if pid not in rostered and player.current_team_id is not None:
                    player.current_team_id = None
                    cleared += 1
        await db.commit()
        run.rows_written = created + moved
        result = {"rostered": len(seen), "created": created, "team_changes": moved, "cleared": cleared,
                  "failed_teams": failed}
        run.detail = str(result)
    return result
