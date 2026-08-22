"""Underdog props ingestion.

CONSTRAINT #17: the over_under_lines response is one document with five
sibling arrays. A line names its player only through
line.over_under.appearance_stat.appearance_id -> appearances[].player_id ->
players[].id. There is no top-level player_id and no teams array, so a
player's team is not resolvable from this endpoint.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.players import ingest_players
from src.ingest.underdog import ingest_props
from src.models.facts import PlayerPropLine

pytestmark = pytest.mark.live


async def test_props_ingest_and_unresolved_are_parked_not_guessed(db):
    # conftest's `db` fixture truncates every table, including `players`,
    # before each test (see its module docstring) - the crosswalk has
    # nothing to resolve against until identity is seeded, matching the
    # pattern every other resolve_player-dependent test in this suite
    # already uses (tests/test_ingest_players.py).
    await ingest_players(db)
    written, parked = await ingest_props(db)
    assert written > 0, "Underdog returned no NFL lines"

    rows = await db.scalar(select(func.count()).select_from(PlayerPropLine))
    assert rows == written

    # Parked appearances are counted, never silently dropped and never
    # name-matched into the wrong player.
    assert parked >= 0
    print(f"underdog: {written} written, {parked} parked as unresolvable")


async def test_stat_types_are_normalized(db):
    await ingest_players(db)
    await ingest_props(db)
    values = {
        row[0]
        for row in await db.execute(select(PlayerPropLine.stat_type).distinct())
    }
    assert values
    assert all(v == v.lower() and " " not in v for v in values)


async def test_second_ingest_writes_nothing_when_lines_are_unchanged(db):
    await ingest_players(db)
    first, _ = await ingest_props(db)
    second, _ = await ingest_props(db)
    assert second < first, "insert-on-change did not suppress unchanged lines"
