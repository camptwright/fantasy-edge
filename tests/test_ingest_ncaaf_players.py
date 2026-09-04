"""NCAAF player seeding (src/ingest/ncaaf_players.py): offline unit tests
against a fake payload shaped like the real API, plus one live smoke test.
Real shape verified live 2026-09-05 against a real ESPN team roster
endpoint (site.api.espn.com/.../teams/{id}/roster).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.identity import resolve_team
from src.ingest.ncaaf_players import _upsert_player, ingest_players
from src.models.identity import Player, PlayerExternalId


def _fake_athlete(athlete_id: str = "5369936", full_name: str = "Stuart Andrews", position: str = "OL") -> dict:
    return {"id": athlete_id, "fullName": full_name, "position": {"abbreviation": position}}


async def test_upsert_player_creates_a_new_player(db):
    created = await _upsert_player(db, _fake_athlete())
    assert created is True

    external = await db.scalar(
        select(PlayerExternalId).where(PlayerExternalId.source == "espn_ncaaf", PlayerExternalId.external_id == "5369936")
    )
    assert external is not None
    player = await db.get(Player, external.player_id)
    assert player.sport == "ncaaf"
    assert player.full_name == "Stuart Andrews"


async def test_upsert_player_is_idempotent_on_external_id(db):
    await _upsert_player(db, _fake_athlete())
    assert await _upsert_player(db, _fake_athlete()) is False

    rows = (await db.execute(select(Player).where(Player.sport == "ncaaf"))).scalars().all()
    assert len(rows) == 1


async def test_upsert_player_skips_a_record_with_no_id_or_name(db):
    assert await _upsert_player(db, {"fullName": "No Id Guy"}) is False
    assert await _upsert_player(db, {"id": "999"}) is False


async def test_ingest_players_is_a_noop_with_no_ncaaf_teams_seeded(db):
    """A fresh database has no NCAAF Team rows yet (those come from ESPN's
    own scoreboard sync) - this must return 0, not error trying to loop
    zero teams' rosters."""
    written = await ingest_players(db)
    assert written == 0


@pytest.mark.live
async def test_live_ingest_seeds_real_players_for_a_seeded_team(db):
    # Seed exactly one real NCAAF team so this test makes one real roster
    # request, not 137.
    await resolve_team(db, "Ohio State Buckeyes", sport="ncaaf")
    await db.commit()

    written = await ingest_players(db)
    assert written > 0, "ESPN returned no roster for a real, seeded NCAAF team"
