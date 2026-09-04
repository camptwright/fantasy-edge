"""recommendation_snapshots - cached LLM narrative over real signals/props.

Revision ID: 0009_recommendation_snapshots
Revises: 0008_nhl_game_id
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_recommendation_snapshots"
down_revision = "0008_nhl_game_id"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recommendation_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_snapshots_generated_at",
        "recommendation_snapshots",
        ["generated_at"],
    )


def downgrade():
    op.drop_index("ix_recommendation_snapshots_generated_at", table_name="recommendation_snapshots")
    op.drop_table("recommendation_snapshots")
