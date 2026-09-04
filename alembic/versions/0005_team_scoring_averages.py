"""Team scoring averages - the totals-market baseline's inputs.

Revision ID: 0005_team_scoring_averages
Revises: 0004_team_ratings
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_team_scoring_averages"
down_revision = "0004_team_ratings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("team_ratings", sa.Column("avg_points_scored", sa.Float(), nullable=True))
    op.add_column("team_ratings", sa.Column("avg_points_allowed", sa.Float(), nullable=True))
    op.add_column(
        "team_ratings",
        sa.Column("games_played", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("team_ratings", "games_played")
    op.drop_column("team_ratings", "avg_points_allowed")
    op.drop_column("team_ratings", "avg_points_scored")
