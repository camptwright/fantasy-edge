"""Per player-game offensive snap counts from nflverse (PFR snap counts).

Verified live 2026-10-12 with nflreadpy: `load_snap_counts([2026])` returns
7,277 rows across weeks 1-5 with columns game_id (nflverse id, e.g.
"2026_01_ARI_LAC"), pfr_player_id, team, offense_snaps, offense_pct (a 0-1
fraction, not a percent), st_snaps. It carries no gsis id; `load_players()`
maps pfr_id -> gsis_id for all but 3 of the 1,810 PFR ids in that sample.

Rows whose player or game cannot be resolved exactly are skipped, never
matched by name: a name join is the Josh Allen bug (see test_ingest_players).

The serving image deliberately lacks nflreadpy, so the scheduled refresh
reads the same release CSVs directly (as src/services/nfl_epa_feed.py does);
verified live 2026-10-12: snap_counts_2026.csv has the columns above and
players.csv carries gsis_id and pfr_id.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingest.identity import resolve_team
from src.ingest.nflverse import _nflreadpy, _number, _records
from src.ingest.runs import record_run
from src.models.facts import Game, PlayerSnapCount
from src.models.identity import Player

SOURCE = "nflverse"
RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"


async def ingest_snap_counts(
    db: AsyncSession, seasons: list[int], *, records=None, players=None
) -> int:
    """Insert snap counts for the given seasons. Returns rows written."""
    if records is None or players is None:
        nfl = _nflreadpy()
        records = _records(nfl.load_snap_counts(seasons)) if records is None else records
        players = _records(nfl.load_players()) if players is None else players
    gsis_by_pfr = {p["pfr_id"]: p["gsis_id"] for p in players if p.get("pfr_id") and p.get("gsis_id")}

    async with record_run(db, f"{SOURCE}:snap_counts") as run:
        player_ids: dict[str, Any] = {}
        game_ids: dict[str, Any] = {}
        team_ids: dict[str, Any] = {}
        for record in records:
            gsis_id = gsis_by_pfr.get(record.get("pfr_player_id"))
            snaps = _number(record.get("offense_snaps"))
            pct = _number(record.get("offense_pct"))
            if not gsis_id or snaps is None or pct is None or not record.get("team"):
                continue
            # Defensive/special-teams-only rows carry no offensive opportunity.
            if snaps <= 0:
                continue
            if gsis_id not in player_ids:
                player_ids[gsis_id] = await db.scalar(select(Player.id).where(Player.gsis_id == gsis_id))
            nflverse_id = record.get("game_id")
            if nflverse_id not in game_ids:
                game_ids[nflverse_id] = await db.scalar(
                    select(Game.id).where(Game.nflverse_game_id == nflverse_id))
            team = record["team"]
            if team not in team_ids:
                try:
                    team_ids[team] = (await resolve_team(db, team)).id
                except LookupError:
                    team_ids[team] = None
            player_id, game_id, team_id = player_ids[gsis_id], game_ids[nflverse_id], team_ids[team]
            if player_id is None or game_id is None or team_id is None:
                continue
            st = _number(record.get("st_snaps"))
            result = await db.execute(
                insert(PlayerSnapCount)
                .values(player_id=player_id, game_id=game_id, team_id=team_id,
                        offense_snaps=int(snaps), offense_pct=pct,
                        st_snaps=None if st is None else int(st), source=SOURCE)
                .on_conflict_do_nothing(index_elements=["player_id", "game_id", "source"])
            )
            run.rows_written += result.rowcount
        await db.commit()
        return run.rows_written


async def refresh_snap_counts(db: AsyncSession, season: int) -> dict[str, int]:
    """Dependency-light scheduled refresh from the nflverse release CSVs."""
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        frames = {}
        for name, path in (("snaps", f"snap_counts/snap_counts_{season}.csv"),
                           ("players", "players/players.csv")):
            response = await client.get(f"{RELEASES}/{path}")
            response.raise_for_status()
            frames[name] = list(csv.DictReader(io.StringIO(response.text)))
    records = [r for r in frames["snaps"] if str(r.get("season")) == str(season)
               and r.get("game_type") in ("REG", "POST")]
    written = await ingest_snap_counts(db, [season], records=records, players=frames["players"])
    return {"season": season, "rows_read": len(records), "rows_written": written}
