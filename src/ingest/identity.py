"""The single place any source looks up or creates a Team.

CONSTRAINT #24: historical seeding and live sync must not create separate
Team rows for the same franchise. nflverse publishes abbreviations ("KC"),
ESPN publishes display names ("Kansas City Chiefs"); neither matches the
other. Both paths run through here, so whichever arrives first creates the
canonical row and the second attaches to it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.identity import Team

_ALIAS_PATH = Path(__file__).resolve().parents[2] / "config" / "team_aliases" / "nfl.yaml"


@lru_cache
def _aliases() -> dict[str, dict[str, str]]:
    """The 32 entries live under a top-level `aliases:` key, each a dict of
    `espn_name` and `espn_id` (verified 2026-08-20 - NOT `name`)."""
    data = yaml.safe_load(_ALIAS_PATH.read_text())
    aliases = data["aliases"]
    for key in aliases:
        # CONSTRAINT #24: an unquoted NO parses as boolean False under YAML 1.1.
        if not isinstance(key, str):
            raise ValueError(f"alias key {key!r} is {type(key)}, not str - quote it")
    return aliases


async def resolve_team(db: AsyncSession, identifier: str) -> Team:
    """Resolve an nflverse abbreviation or an ESPN name to one canonical Team."""
    entry = _aliases().get(identifier)
    if entry is None:
        for abbr, candidate in _aliases().items():
            if candidate.get("espn_name") == identifier or candidate.get("espn_id") == identifier:
                identifier, entry = abbr, candidate
                break
    if entry is None:
        raise LookupError(f"no NFL team alias for {identifier!r}")

    existing = await db.scalar(select(Team).where(Team.nflverse_abbr == identifier))
    if existing is not None:
        return existing

    # RULING (found reviewing Task 1): nfl.yaml deliberately maps both WAS
    # and WSH to espn_id 28 - nflverse's Washington abbreviation changed
    # across data vintages and the file covers both defensively (see its
    # own comment). Team.espn_id is UNIQUE, so if nflverse's real history
    # uses both abbreviations across seasons, looking up by nflverse_abbr
    # alone would attempt a second insert with the same espn_id and crash
    # ingestion outright. Check espn_id before creating a new row.
    existing = await db.scalar(select(Team).where(Team.espn_id == str(entry["espn_id"])))
    if existing is not None:
        return existing

    team = Team(
        nflverse_abbr=identifier,
        espn_id=str(entry["espn_id"]),
        name=entry["espn_name"],
    )
    db.add(team)
    await db.flush()
    return team
