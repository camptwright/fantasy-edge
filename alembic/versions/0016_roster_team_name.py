"""sleeper_rosters.team_name - the trade recommender needs a human
display name for each roster, which neither platform's roster object
carries itself (see src/models/sleeper.py's docstring on the column).

Revision ID: 0016_roster_team_name
Revises: 0015_roster_owner_id_width
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_roster_team_name"
down_revision = "0015_roster_owner_id_width"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sleeper_rosters", sa.Column("team_name", sa.String(length=160), nullable=True))


def downgrade():
    op.drop_column("sleeper_rosters", "team_name")
