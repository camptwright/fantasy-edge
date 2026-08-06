"""Constraint #24's fix: `scripts/seed_historical.py` and
`GameSyncAgent._resolve_team_id` used to look up Team rows by raw
historical-loader name and raw ESPN-synced name independently, with no
shared identity between them - two different spellings for the same
team ("KC" vs "Kansas City Chiefs") silently created two different Team
rows, so a live-synced game's home_team_id/away_team_id stayed NULL even
after historical seeding.

`resolve_team()` is now the one place either caller looks a team up:
run a raw identifier through `config/team_aliases/<sport>.yaml` (if that
sport has a crosswalk file) to get ESPN's canonical name/espn_id, then
look up a Team row by that canonical identity - regardless of which
path (historical seed or live ESPN sync) ran first and created the row.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_team_aliases
from src.models.orm import Team


async def resolve_team(
    db: AsyncSession,
    sport: str,
    raw_name: str | None,
    espn_id: str | None = None,
    *,
    create: bool = False,
) -> str | None:
    """Resolve (sport, raw_name, espn_id) to a canonical Team.id.

    `create=False` (GameSyncAgent's live-sync path): read-only, returns
    None if no canonical row exists yet - matches the prior behavior of
    never creating a Team row during live sync.

    `create=True` (seed_historical.py's backfill path): creates the
    canonical row on a miss, same upsert-race handling
    `_get_or_create_team` used to do itself.
    """
    if not raw_name and not espn_id:
        return None

    alias = get_team_aliases(sport).get(raw_name) if raw_name else None
    canonical_name = alias["espn_name"] if alias else raw_name
    canonical_espn_id = espn_id or (alias["espn_id"] if alias else None)

    if canonical_espn_id:
        result = await db.execute(
            select(Team.id).where(Team.sport == sport, Team.espn_id == canonical_espn_id)
        )
        row = result.first()
        if row:
            return str(row[0])

    if canonical_name:
        result = await db.execute(
            select(Team.id).where(Team.sport == sport, Team.name == canonical_name)
        )
        row = result.first()
        if row:
            return str(row[0])

    if not create or not canonical_name:
        return None

    stmt = (
        pg_insert(Team)
        .values(sport=sport, name=canonical_name, espn_id=canonical_espn_id)
        .on_conflict_do_nothing(constraint="uq_team_sport_name")
        .returning(Team.id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row:
        return str(row[0])

    # Conflict raced us (another row inserted between the check and
    # insert) - re-select rather than error, since the row now exists
    # either way.
    result = await db.execute(
        select(Team.id).where(Team.sport == sport, Team.name == canonical_name)
    )
    return str(result.first()[0])
