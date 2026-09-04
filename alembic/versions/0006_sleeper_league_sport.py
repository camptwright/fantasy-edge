"""sleeper_leagues.sport - Sleeper sync now covers more than one sport.

Revision ID: 0006_sleeper_league_sport
Revises: 0005_team_scoring_averages
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_sleeper_league_sport"
down_revision = "0005_team_scoring_averages"
branch_labels = None
depends_on = None


def upgrade():
    # Every row synced before this migration is an NFL league - Sleeper
    # sync was NFL-only until now - so backfilling 'nfl' is an accurate
    # value, not a placeholder.
    op.add_column(
        "sleeper_leagues",
        sa.Column("sport", sa.String(length=8), nullable=False, server_default="nfl"),
    )


def downgrade():
    op.drop_column("sleeper_leagues", "sport")
