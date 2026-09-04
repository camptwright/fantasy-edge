"""src/ingest/prizepicks.py against a real (trimmed) live response.

Fixture captured live 2026-09-03 (tests/fixtures/prizepicks.json): six
standard, non-promo, two-sided NFL projections. No player is seeded here,
so every row is expected to park - this mirrors
test_ingest_underdog_offline.py's own "nothing seeded, everything parks"
shape, which is what actually proves the sport/league filter and the
standard/promo/goblin-demon filter are both being applied before
resolve_player ever runs, not silently passing everything through.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from src.ingest.prizepicks import ingest_props
from src.models.facts import PlayerPropLine
from src.models.identity import Player

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "prizepicks.json").read_text())


async def test_unresolved_players_are_parked_not_dropped_silently(db):
    with patch(
        "src.ingest.prizepicks.PrizePicksScraper.fetch_json", new=AsyncMock(return_value=PAYLOAD)
    ):
        written, parked = await ingest_props(db)

    assert written == 0
    assert parked == 6  # every fixture projection is NFL/standard/two-sided


async def test_a_seeded_player_resolves_with_no_american_odds(db):
    """PrizePicks has no price field at all - over/under_price_american
    must stay null (never fabricated) even though the row is written."""
    player = Player(sport="nfl", full_name="Drake Maye", position="QB")
    db.add(player)
    await db.flush()

    with patch(
        "src.ingest.prizepicks.PrizePicksScraper.fetch_json", new=AsyncMock(return_value=PAYLOAD)
    ):
        written, parked = await ingest_props(db)

    # Fixture has two Drake Maye (215664) projections: "Pass+Rush Yds" and
    # "Pass Yards" - both should resolve to the one seeded player.
    assert written == 2
    assert parked == 4

    rows = (
        await db.execute(select(PlayerPropLine).where(PlayerPropLine.player_id == player.id))
    ).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert row.over_price_american is None
        assert row.under_price_american is None
        assert row.source == "prizepicks"
