"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-02

Creates the eleven core tables. Table order matters: foreign keys are declared
inline, so a referenced table must exist first.

gen_random_uuid() is a Postgres 13+ builtin, so no pgcrypto extension is
required for the UUID defaults.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("abbreviation", sa.String(16)),
        sa.Column("espn_id", sa.String(32)),
        sa.Column("odds_api_name", sa.String(128)),
        sa.Column("conference", sa.String(64)),
        sa.Column("division", sa.String(64)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("sport", "name", name="uq_team_sport_name"),
    )
    op.create_index("ix_teams_sport", "teams", ["sport"])
    op.create_index("ix_teams_espn_id", "teams", ["espn_id"])
    op.create_index("ix_teams_odds_api_name", "teams", ["odds_api_name"])
    op.create_index("ix_teams_created_at", "teams", ["created_at"])
    op.create_index("ix_team_sport_espn", "teams", ["sport", "espn_id"])

    op.create_table(
        "players",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("team_id", UUID, sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("position", sa.String(16)),
        sa.Column("espn_id", sa.String(32)),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("sport", "normalized_name", "team_id", name="uq_player_ident"),
    )
    op.create_index("ix_players_sport", "players", ["sport"])
    op.create_index("ix_players_full_name", "players", ["full_name"])
    op.create_index("ix_players_normalized_name", "players", ["normalized_name"])
    op.create_index("ix_players_position", "players", ["position"])
    op.create_index("ix_players_espn_id", "players", ["espn_id"])
    op.create_index("ix_players_created_at", "players", ["created_at"])

    op.create_table(
        "games",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("espn_event_id", sa.String(64)),
        sa.Column("odds_api_event_id", sa.String(64)),
        sa.Column("home_team_id", UUID, sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("away_team_id", UUID, sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("home_team_name", sa.String(128)),
        sa.Column("away_team_name", sa.String(128)),
        # Nullable by design - see constraint #2 in CLAUDE.md.
        sa.Column("game_time", TS),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("home_score", sa.Integer),
        sa.Column("away_score", sa.Integer),
        sa.Column("season", sa.Integer),
        sa.Column("week", sa.Integer),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('scheduled','live','final','postponed','cancelled')",
            name="ck_game_status",
        ),
        sa.UniqueConstraint("sport", "espn_event_id", name="uq_game_espn"),
    )
    op.create_index("ix_games_sport", "games", ["sport"])
    op.create_index("ix_games_espn_event_id", "games", ["espn_event_id"])
    op.create_index("ix_games_odds_api_event_id", "games", ["odds_api_event_id"])
    op.create_index("ix_games_game_time", "games", ["game_time"])
    op.create_index("ix_games_status", "games", ["status"])
    op.create_index("ix_games_season", "games", ["season"])
    op.create_index("ix_games_created_at", "games", ["created_at"])
    op.create_index("ix_game_sport_time_status", "games", ["sport", "game_time", "status"])

    op.create_table(
        "odds_snapshots",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("game_id", UUID, sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("bookmaker", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(128), nullable=False),
        sa.Column("price_american", sa.Integer),
        sa.Column("price_decimal", sa.Float),
        sa.Column("point", sa.Float),
        sa.Column("implied_probability", sa.Float),
        sa.Column("captured_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_odds_snapshots_game_id", "odds_snapshots", ["game_id"])
    op.create_index("ix_odds_snapshots_sport", "odds_snapshots", ["sport"])
    op.create_index("ix_odds_snapshots_bookmaker", "odds_snapshots", ["bookmaker"])
    op.create_index("ix_odds_snapshots_market", "odds_snapshots", ["market"])
    op.create_index("ix_odds_snapshots_captured_at", "odds_snapshots", ["captured_at"])
    op.create_index(
        "ix_odds_game_market_book",
        "odds_snapshots",
        ["game_id", "market", "bookmaker", "captured_at"],
    )

    op.create_table(
        "model_outputs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("game_id", UUID, sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(32)),
        sa.Column("home_win_probability", sa.Float),
        sa.Column("away_win_probability", sa.Float),
        sa.Column("predicted_total", sa.Float),
        sa.Column("predicted_spread", sa.Float),
        sa.Column("features", postgresql.JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_model_outputs_game_id", "model_outputs", ["game_id"])
    op.create_index("ix_model_outputs_sport", "model_outputs", ["sport"])
    op.create_index("ix_model_outputs_created_at", "model_outputs", ["created_at"])
    op.create_index("ix_model_game_name", "model_outputs", ["game_id", "model_name", "created_at"])

    op.create_table(
        "bet_signals",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("game_id", UUID, sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("selection", sa.String(128), nullable=False),
        sa.Column("bookmaker", sa.String(64), nullable=False),
        sa.Column("point", sa.Float),
        sa.Column("price_american", sa.Integer),
        sa.Column("model_probability", sa.Float, nullable=False),
        sa.Column("fair_probability", sa.Float),
        sa.Column("implied_probability", sa.Float),
        sa.Column("ev_percent", sa.Float, nullable=False),
        sa.Column("kelly_fraction", sa.Float),
        sa.Column("stake_units", sa.Float),
        sa.Column("confidence", sa.String(16)),
        sa.Column("tier", sa.String(16)),
        sa.Column("closing_price_american", sa.Integer),
        sa.Column("closing_implied_probability", sa.Float),
        sa.Column("clv_percent", sa.Float),
        sa.Column("clv_captured_at", TS),
        sa.Column("result", sa.String(16)),
        sa.Column("alerted_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_bet_signals_game_id", "bet_signals", ["game_id"])
    op.create_index("ix_bet_signals_sport", "bet_signals", ["sport"])
    op.create_index("ix_bet_signals_market", "bet_signals", ["market"])
    op.create_index("ix_bet_signals_ev_percent", "bet_signals", ["ev_percent"])
    op.create_index("ix_bet_signals_tier", "bet_signals", ["tier"])
    op.create_index("ix_bet_signals_result", "bet_signals", ["result"])
    op.create_index("ix_bet_signals_created_at", "bet_signals", ["created_at"])
    op.create_index("ix_signal_sport_ev", "bet_signals", ["sport", "ev_percent"])
    op.create_index(
        "ix_signal_dedupe", "bet_signals", ["game_id", "market", "selection", "bookmaker"]
    )

    op.create_table(
        "player_prop_lines",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("player_name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("player_id", UUID, sa.ForeignKey("players.id", ondelete="SET NULL")),
        sa.Column("game_id", UUID, sa.ForeignKey("games.id", ondelete="SET NULL")),
        sa.Column("team_name", sa.String(128)),
        sa.Column("opponent_name", sa.String(128)),
        sa.Column("stat_type", sa.String(48), nullable=False),
        sa.Column("line", sa.Float, nullable=False),
        sa.Column("over_price_american", sa.Integer),
        sa.Column("under_price_american", sa.Integer),
        sa.Column("projection", sa.Float),
        sa.Column("edge_percent", sa.Float),
        sa.Column("captured_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_player_prop_lines_sport", "player_prop_lines", ["sport"])
    op.create_index("ix_player_prop_lines_source", "player_prop_lines", ["source"])
    op.create_index("ix_player_prop_lines_player_name", "player_prop_lines", ["player_name"])
    op.create_index(
        "ix_player_prop_lines_normalized_name", "player_prop_lines", ["normalized_name"]
    )
    op.create_index("ix_player_prop_lines_game_id", "player_prop_lines", ["game_id"])
    op.create_index("ix_player_prop_lines_stat_type", "player_prop_lines", ["stat_type"])
    op.create_index("ix_player_prop_lines_edge_percent", "player_prop_lines", ["edge_percent"])
    op.create_index("ix_player_prop_lines_captured_at", "player_prop_lines", ["captured_at"])
    # Supports the DISTINCT ON (player_name, stat_type, source) ORDER BY
    # captured_at DESC that every props list endpoint must use (constraint #7).
    op.create_index(
        "ix_prop_distinct_on",
        "player_prop_lines",
        ["player_name", "stat_type", "source", "captured_at"],
    )
    op.create_index(
        "ix_prop_sport_stat", "player_prop_lines", ["sport", "stat_type", "captured_at"]
    )
    # Constraint #6: dedup enforced in Postgres, one row per player/stat/source/
    # line/day. The ingest path uses INSERT ... WHERE NOT EXISTS; this index is
    # the backstop if a concurrent poll slips past that check.
    #
    # NOT date(captured_at): on a timestamptz that function is STABLE, not
    # IMMUTABLE (its result depends on the session TimeZone), and Postgres
    # rejects it outright - "functions in index expression must be marked
    # IMMUTABLE" - which rolls back the entire migration. Pinning the zone to
    # UTC makes the expression immutable, and UTC is what captured_at is
    # already stored in.
    op.create_index(
        "uq_prop_daily",
        "player_prop_lines",
        [
            "player_name",
            "stat_type",
            "source",
            "line",
            sa.text("((captured_at AT TIME ZONE 'UTC')::date)"),
        ],
        unique=True,
    )

    op.create_table(
        "parlays",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32)),
        sa.Column("title", sa.String(200)),
        sa.Column("rationale", sa.Text),
        sa.Column("combined_odds_american", sa.Integer),
        sa.Column("combined_probability", sa.Float),
        sa.Column("ev_percent", sa.Float),
        sa.Column("generator", sa.String(32)),
        sa.Column("result", sa.String(16)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_parlays_sport", "parlays", ["sport"])
    op.create_index("ix_parlays_result", "parlays", ["result"])
    op.create_index("ix_parlays_created_at", "parlays", ["created_at"])

    op.create_table(
        "parlay_legs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("parlay_id", UUID, sa.ForeignKey("parlays.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "prop_line_id", UUID, sa.ForeignKey("player_prop_lines.id", ondelete="SET NULL")
        ),
        sa.Column("bet_signal_id", UUID, sa.ForeignKey("bet_signals.id", ondelete="SET NULL")),
        sa.Column("description", sa.String(256), nullable=False),
        sa.Column("selection", sa.String(128)),
        sa.Column("price_american", sa.Integer),
        sa.Column("probability", sa.Float),
        sa.Column("result", sa.String(16)),
    )
    op.create_index("ix_parlay_legs_parlay_id", "parlay_legs", ["parlay_id"])

    op.create_table(
        "power_rankings",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("team_id", UUID, sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("elo_rating", sa.Float, nullable=False),
        sa.Column("rank", sa.Integer),
        sa.Column("prev_rank", sa.Integer),
        sa.Column("season", sa.Integer),
        sa.Column("as_of", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_power_rankings_sport", "power_rankings", ["sport"])
    op.create_index("ix_power_rankings_team_id", "power_rankings", ["team_id"])
    op.create_index("ix_power_rankings_season", "power_rankings", ["season"])
    op.create_index("ix_power_rankings_as_of", "power_rankings", ["as_of"])
    op.create_index("ix_ranking_sport_asof", "power_rankings", ["sport", "as_of"])

    op.create_table(
        "dfs_lineups",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("site", sa.String(16), nullable=False),
        sa.Column("slate_date", TS),
        sa.Column("total_salary", sa.Integer),
        sa.Column("projected_points", sa.Float),
        sa.Column("players", sa.JSON),
        sa.Column("locked_players", sa.JSON),
        sa.Column("excluded_players", sa.JSON),
        sa.Column("actual_points", sa.Float),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("site IN ('draftkings','fanduel')", name="ck_dfs_site"),
    )
    op.create_index("ix_dfs_lineups_sport", "dfs_lineups", ["sport"])
    op.create_index("ix_dfs_lineups_slate_date", "dfs_lineups", ["slate_date"])
    op.create_index("ix_dfs_lineups_created_at", "dfs_lineups", ["created_at"])


def downgrade() -> None:
    for table in (
        "dfs_lineups",
        "power_rankings",
        "parlay_legs",
        "parlays",
        "player_prop_lines",
        "bet_signals",
        "model_outputs",
        "odds_snapshots",
        "games",
        "players",
        "teams",
    ):
        op.drop_table(table)
