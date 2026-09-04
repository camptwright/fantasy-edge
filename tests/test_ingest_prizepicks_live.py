"""Live canary for src/ingest/prizepicks.py - the public projections
endpoint is undocumented and can change shape without notice, which a
fixture-based test cannot catch."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.players import ingest_players
from src.ingest.prizepicks import ingest_props
from src.models.facts import PlayerPropLine

pytestmark = pytest.mark.live


async def test_props_ingest_and_carry_no_fabricated_price(db):
    await ingest_players(db)
    written, parked = await ingest_props(db)
    assert written > 0, "PrizePicks returned no matchable NFL/NCAAF lines"

    rows = await db.scalar(select(func.count()).select_from(PlayerPropLine))
    assert rows == written
    assert parked >= 0

    prices = (
        await db.execute(
            select(PlayerPropLine.over_price_american, PlayerPropLine.under_price_american)
        )
    ).all()
    assert all(over is None and under is None for over, under in prices)
    print(f"prizepicks: {written} written, {parked} parked as unresolvable")
