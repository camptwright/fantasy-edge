"""The migrated schema must contain the complete application table set."""

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
    "sleeper_leagues",
    "sleeper_rosters",
    "sleeper_league_snapshots",
    "team_ratings",
    "recommendation_snapshots",
    "calibration_reports",
    "quote_availability",
    "result_sync_states",
    "result_corrections",
    "ledger_bets",
    "ledger_events",
    "ledger_policies",
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


async def test_sport_column_exists_on_teams_and_games(db):
    """Overrides the original data-foundation plan's "NFL only, no sport
    column" constraint (approved 2026-08-29 to add NCAAF - see CLAUDE.md).
    Both tables must carry it, not just teams: games denormalizes sport so
    prop/signal/ranking queries filter by a plain column, not a join."""
    rows = await db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'sport'"
        )
    )
    tables_with_sport = {r[0] for r in rows}
    assert {"teams", "players", "games"} <= tables_with_sport


async def test_team_identity_is_unique_per_sport_not_globally(db):
    """ESPN's numeric team ids are scoped per sport - an NFL and an NCAAF
    team can share an id. Uniqueness must be scoped to (sport, espn_id),
    not a bare unique on espn_id alone."""
    rows = await db.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'teams'")
    )
    defs = " ".join(r[0] for r in rows).upper()
    assert "SPORT" in defs and "ESPN_ID" in defs
