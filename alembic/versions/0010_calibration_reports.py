"""calibration_reports - walk-forward backtest results (src/services/backtest.py).

Revision ID: 0010_calibration_reports
Revises: 0009_recommendation_snapshots
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_calibration_reports"
down_revision = "0009_recommendation_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calibration_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sport", sa.String(length=8), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("seasons_used", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("passed_gate", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_calibration_reports_sport_market",
        "calibration_reports",
        ["sport", "market"],
    )


def downgrade():
    op.drop_index("ix_calibration_reports_sport_market", table_name="calibration_reports")
    op.drop_table("calibration_reports")
