"""The single place any source looks up or creates a Team.

CONSTRAINT #24: historical seeding and live sync must not create separate
Team rows for the same franchise. nflverse publishes abbreviations ("KC"),
ESPN publishes display names ("Kansas City Chiefs"); neither matches the
other. Both paths run through here, so whichever arrives first creates the
canonical row and the second attaches to it.

Sport dimension (added 2026-08-29, overriding the data-foundation plan's
"NFL only" constraint - see CLAUDE.md): every alias lookup and every Team
row is scoped by sport. ESPN's own numeric team ids are assigned per sport,
not globally, so an unscoped lookup could silently attach an NCAAF result
to an NFL team id that happens to match.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.identity import Player, PlayerExternalId, Team
from src.utils.normalize import normalize_player_name

_ALIAS_DIR = Path(__file__).resolve().parents[2] / "config" / "team_aliases"


@lru_cache
def _aliases(sport: str) -> dict[str, dict[str, str]]:
    """Each sport's file nests its entries under a top-level `aliases:` key,
    each a dict of `espn_name` and `espn_id` (verified 2026-08-20 for NFL,
    2026-08-29 for NCAAF - NOT `name`)."""
    data = yaml.safe_load((_ALIAS_DIR / f"{sport}.yaml").read_text())
    aliases = data["aliases"]
    for key in aliases:
        # CONSTRAINT #24: an unquoted NO parses as boolean False under YAML 1.1.
        if not isinstance(key, str):
            raise ValueError(f"alias key {key!r} is {type(key)}, not str - quote it")
    return aliases


async def resolve_team(db: AsyncSession, identifier: str, sport: str = "nfl") -> Team:
    """Resolve a source abbreviation or an ESPN name to one canonical Team,
    scoped to the given sport."""
    aliases = _aliases(sport)
    entry = aliases.get(identifier)
    if entry is None:
        for abbr, candidate in aliases.items():
            if candidate.get("espn_name") == identifier or candidate.get("espn_id") == identifier:
                identifier, entry = abbr, candidate
                break
    if entry is None:
        raise LookupError(f"no {sport} team alias for {identifier!r}")

    existing = await db.scalar(
        select(Team).where(Team.sport == sport, Team.nflverse_abbr == identifier)
    )
    if existing is not None:
        return existing

    # RULING (found reviewing Task 1): nfl.yaml deliberately maps both WAS
    # and WSH to espn_id 28 - nflverse's Washington abbreviation changed
    # across data vintages and the file covers both defensively (see its
    # own comment). Team.espn_id is unique per sport, so if nflverse's real
    # history uses both abbreviations across seasons, looking up by
    # nflverse_abbr alone would attempt a second insert with the same
    # espn_id and crash ingestion outright. Check espn_id before creating a
    # new row.
    existing = await db.scalar(
        select(Team).where(Team.sport == sport, Team.espn_id == str(entry["espn_id"]))
    )
    if existing is not None:
        return existing

    team = Team(
        sport=sport,
        nflverse_abbr=identifier,
        espn_id=str(entry["espn_id"]),
        name=entry["espn_name"],
    )
    db.add(team)
    await db.flush()
    return team


async def resolve_verified_espn_team(db: AsyncSession, metadata: dict, sport: str) -> Team:
    """Native identity from an ESPN schedule, for historical coverage only.

    No name match, alias invention, current-rating initialization, or promotion.
    Abbreviation collisions fail closed rather than reassigning an existing team.
    """
    external = str(metadata.get('id', ''))
    name, abbreviation = metadata.get('displayName'), metadata.get('abbreviation')
    if (sport not in ('nfl', 'ncaaf') or not external.isdigit() or len(external) > 16 or
        not isinstance(name, str) or not 0 < len(name) <= 64 or
        not isinstance(abbreviation, str) or not 0 < len(abbreviation) <= 8):
        raise ValueError('invalid verified ESPN team identity')
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                     {'key': f'espn-team:{sport}:{external}'})
    existing = await db.scalar(select(Team).where(Team.sport == sport, Team.espn_id == external))
    if existing:
        return existing
    collision = await db.scalar(select(Team).where(Team.sport == sport, Team.nflverse_abbr == abbreviation))
    if collision:
        raise ValueError('ESPN team abbreviation collision')
    team = Team(sport=sport, espn_id=external, nflverse_abbr=abbreviation, name=name)
    db.add(team)
    await db.flush()
    return team


async def resolve_player(
    db: AsyncSession,
    source: str,
    external_id: str,
    full_name: str,
    position: str | None = None,
    sport: str = "nfl",
) -> Player | None:
    """Resolve a source-specific player id to one canonical Player, scoped to
    the given sport.

    Returns None when the identifier is unknown and cannot be matched without
    guessing. Callers must park the observation rather than fall back to a
    name match: two active players are named Josh Allen, and a wrong match
    poisons the training set silently. NCAAF's much larger player pool raises
    that risk further, which is why every candidate query below is filtered
    to Player.sport == sport rather than searched name-only across sports
    that share no roster overlap.
    """
    mapped = await db.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.source == source,
            PlayerExternalId.external_id == external_id,
        )
    )
    if mapped is not None:
        player = await db.get(Player, mapped.player_id)
        return player if player is not None and player.sport == sport else None

    candidates = list(
        (
            await db.execute(
                select(Player).where(Player.full_name == full_name, Player.sport == sport)
            )
        ).scalars()
    )
    if not candidates:
        # Exact match found nothing. Suffixes are the known gap
        # (normalize_player_name's own docstring: "Ken Griffey Jr." vs
        # "Ken Griffey" - same person, different provider conventions).
        # Only retried on a ZERO-candidate miss, never added to an
        # already-ambiguous multi-candidate result, so this cannot widen
        # the Josh Allen collision case - it only recovers exact matches
        # that differ purely by a suffix.
        target = normalize_player_name(full_name)
        same_sport = (
            (await db.execute(select(Player).where(Player.sport == sport))).scalars().all()
        )
        candidates = [
            p for p in same_sport if normalize_player_name(p.full_name) == target
        ]
    if position is not None:
        candidates = [c for c in candidates if c.position == position] or candidates

    if len(candidates) != 1:
        # Zero candidates: unknown player. More than one: ambiguous, and this
        # is exactly the Josh Allen case. Both are parked, never guessed.
        return None

    player = candidates[0]
    db.add(PlayerExternalId(player_id=player.id, source=source, external_id=external_id))
    await db.flush()
    return player
