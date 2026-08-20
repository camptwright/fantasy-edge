"""The migration must produce exactly the ten tables the spec names."""

from __future__ import annotations

from sqlalchemy import text

EXPECTED_TABLES = {
    "teams",
    "players",
    "player_external_ids",
    "games",
    "team_market_lines",
    "player_prop_lines",
    "player_game_stats",
    "model_artifacts",
    "model_predictions",
    "ingestion_runs",
}


async def test_migration_creates_exactly_the_expected_tables(db):
    rows = await db.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )
    )
    assert {r[0] for r in rows} == EXPECTED_TABLES


async def test_player_external_id_is_unique_per_source(db):
    """Two sources may reuse an id string; one source may not map it twice."""
    rows = await db.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'player_external_ids'"
        )
    )
    defs = " ".join(r[0] for r in rows)
    assert "UNIQUE" in defs.upper()
    assert "source" in defs and "external_id" in defs


async def test_player_game_stat_is_unique_per_player_game_stat_type(db):
    rows = await db.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'player_game_stats'")
    )
    defs = " ".join(r[0] for r in rows).upper()
    assert "UNIQUE" in defs
    for column in ("PLAYER_ID", "GAME_ID", "STAT_TYPE"):
        assert column in defs


async def test_no_sport_column_survives_anywhere(db):
    """NFL only. A sport column is how multi-sport branching creeps back."""
    rows = await db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'sport'"
        )
    )
    assert list(rows) == []
