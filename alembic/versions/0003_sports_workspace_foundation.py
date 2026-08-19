"""add normalized Sports provenance and shared-workspace tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def uid() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.create_table(
        "sports_provider_sources",
        uid(),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("permission_status", sa.String(24), nullable=False, server_default="review"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sports_provider_external_ids",
        uid(),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sports_provider_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_id", "entity_type", "external_id", name="uq_sports_provider_entity"),
    )
    op.create_table(
        "sports_event_participants",
        uid(),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("players.id", ondelete="SET NULL")),
        sa.Column("role", sa.String(24), nullable=False),
    )
    op.create_index("ix_sports_event_participant_event", "sports_event_participants", ["event_id"])
    op.create_table(
        "sports_team_identity_crosswalks",
        uid(),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("canonical_team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("alias", sa.String(128)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("sport", "league", "provider", "external_id", name="uq_sports_team_crosswalk"),
    )
    op.create_table(
        "sports_market_assessments",
        uid(),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("market", sa.String(48), nullable=False),
        sa.Column("selection", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_reason", sa.String(256)),
        sa.Column("probability", sa.Float),
        sa.Column("fair_price_american", sa.Integer),
        sa.Column("edge_percent", sa.Float),
        sa.Column("estimated_value_percent", sa.Float),
        sa.Column("model_version", sa.String(64)),
        sa.Column("source_snapshot_ids", sa.JSON),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sports_market_assessments_event_id", "sports_market_assessments", ["event_id"])
    op.create_index("ix_sports_market_assessments_status", "sports_market_assessments", ["status"])
    op.create_table(
        "sports_favorites",
        uid(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("canonical_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("sport", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "canonical_id", name="uq_sports_favorite"),
    )
    op.create_table(
        "sports_paper_positions",
        uid(),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sports_market_assessments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assumed_price_american", sa.Integer, nullable=False),
        sa.Column("stake_units", sa.Float, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sports_paper_positions")
    op.drop_table("sports_favorites")
    op.drop_index("ix_sports_market_assessments_status", table_name="sports_market_assessments")
    op.drop_index("ix_sports_market_assessments_event_id", table_name="sports_market_assessments")
    op.drop_table("sports_market_assessments")
    op.drop_table("sports_team_identity_crosswalks")
    op.drop_index("ix_sports_event_participant_event", table_name="sports_event_participants")
    op.drop_table("sports_event_participants")
    op.drop_table("sports_provider_external_ids")
    op.drop_table("sports_provider_sources")
