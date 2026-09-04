"""MLB player seeding (src/ingest/mlb_players.py): offline unit tests
against a fake payload shaped like the real API, plus one live smoke test.
Real shape verified live 2026-09-05 against statsapi.mlb.com/api/v1/sports/
1/players (~1,470 people in one call).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.mlb_players import _upsert_player
from src.models.identity import Player, PlayerExternalId


def _fake_person(person_id: int = 671096, full_name: str = "Andrew Abbott", position: str = "P") -> dict:
    return {"id": person_id, "fullName": full_name, "primaryPosition": {"abbreviation": position}}


async def test_upsert_player_creates_a_new_player(db):
    created = await _upsert_player(db, _fake_person())
    assert created is True

    external = await db.scalar(
        select(PlayerExternalId).where(PlayerExternalId.source == "mlb_stats_api", PlayerExternalId.external_id == "671096")
    )
    assert external is not None
    player = await db.get(Player, external.player_id)
    assert player.sport == "mlb"
    assert player.full_name == "Andrew Abbott"
    assert player.position == "P"


async def test_upsert_player_is_idempotent_on_external_id(db):
    await _upsert_player(db, _fake_person())
    created_again = await _upsert_player(db, _fake_person())
    assert created_again is False

    rows = (await db.execute(select(Player).where(Player.sport == "mlb"))).scalars().all()
    assert len(rows) == 1


async def test_upsert_player_skips_a_record_with_no_id_or_name(db):
    assert await _upsert_player(db, {"fullName": "No Id Guy"}) is False
    assert await _upsert_player(db, {"id": 999}) is False


@pytest.mark.live
async def test_live_ingest_seeds_real_mlb_players(db):
    from src.ingest.mlb_players import ingest_players

    written = await ingest_players(db)
    assert written > 1000, "MLB Stats API returned far fewer players than a real season roster"
