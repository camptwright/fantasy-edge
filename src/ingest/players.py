"""Player identity and long-form per-game statistics from nflverse."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingest.identity import resolve_team
from src.ingest.nflverse import _nflreadpy, _number, _records
from src.ingest.runs import record_run
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, PlayerExternalId
from src.utils.normalize import normalize_stat_type

SOURCE = "nflverse"

# nflverse player-stat columns worth storing. Anything not listed is ignored
# rather than stored blindly; prop markets are the reason a column earns a
# row.
#
# Verified live 2026-08-20 against nflreadpy.load_player_stats([2025]) - the
# brief's first guess used a bare "interceptions" column, but the real frame
# has no such column. Passing interceptions are `passing_interceptions`; the
# rest of the brief's names (completions, attempts, passing_yards,
# passing_tds, carries, rushing_yards, rushing_tds, receptions, targets,
# receiving_yards, receiving_tds) matched exactly.
STAT_COLUMNS = [
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
]


async def ingest_players(db: AsyncSession) -> int:
    nfl = _nflreadpy()
    async with record_run(db, f"{SOURCE}:players") as run:
        for record in _records(nfl.load_players()):
            gsis_id = record.get("gsis_id")
            if not gsis_id:
                continue
            existing = await db.scalar(select(Player).where(Player.gsis_id == gsis_id))
            if existing is not None:
                continue
            player = Player(
                gsis_id=gsis_id,
                full_name=record.get("display_name") or record.get("full_name") or "",
                position=record.get("position"),
            )
            db.add(player)
            await db.flush()
            db.add(
                PlayerExternalId(player_id=player.id, source=SOURCE, external_id=gsis_id)
            )
            run.rows_written += 1
        await db.commit()
        return run.rows_written


async def ingest_player_stats(db: AsyncSession, seasons: list[int]) -> int:
    nfl = _nflreadpy()
    records = _records(nfl.load_player_stats(seasons))

    async with record_run(db, f"{SOURCE}:player_stats") as run:
        for record in records:
            gsis_id = record.get("player_id")
            if not gsis_id:
                continue
            player = await db.scalar(select(Player).where(Player.gsis_id == gsis_id))
            if player is None:
                continue

            game = await _game_for(db, record)
            if game is None:
                continue

            for column in STAT_COLUMNS:
                value = _number(record.get(column))
                if value is None:
                    continue
                await db.execute(
                    insert(PlayerGameStat)
                    .values(
                        player_id=player.id,
                        game_id=game.id,
                        stat_type=normalize_stat_type(column),
                        value=value,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["player_id", "game_id", "stat_type"]
                    )
                )
                run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _game_for(db: AsyncSession, record: dict[str, Any]) -> Game | None:
    """Resolve a player-stat row to its game.

    nflverse player stats carry season, week, and the player's team - not a
    game_id. Season and week alone match roughly sixteen games, so the team
    is REQUIRED to disambiguate; without it every player's statistics would
    attach to an arbitrary game that week.

    The team column is `recent_team` in nflreadr's published dictionary;
    the live nflverse release ingested here (verified 2026-08-20) actually
    exposes it as `team`. Both are accepted rather than guessing which this
    version emits.
    """
    season, week = record.get("season"), record.get("week")
    abbr = record.get("recent_team") or record.get("team")
    if season is None or week is None or not abbr:
        return None

    try:
        team = await resolve_team(db, str(abbr))
    except LookupError:
        # An abbreviation not present in config/team_aliases/nfl.yaml. Park
        # the record rather than crashing the whole ingestion run - the same
        # policy resolve_player() applies to unrecognised identifiers.
        return None

    return await db.scalar(
        select(Game).where(
            Game.season == int(season),
            Game.week == int(week),
            or_(Game.home_team_id == team.id, Game.away_team_id == team.id),
        )
    )
