"""sleeper_rosters.owner_id 32 -> 40 chars - ESPN's SWID-derived owner id
is a 36-char dash-stripped UUID, which doesn't fit Sleeper's own shorter
numeric snowflake id width. Found live 2026-09-09: the first real ESPN
Fantasy sync failed with StringDataRightTruncationError against the
original column.

Revision ID: 0015_roster_owner_id_width
Revises: 0014_league_platform
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_roster_owner_id_width"
down_revision = "0014_league_platform"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("sleeper_rosters", "owner_id", type_=sa.String(length=40))


def downgrade():
    op.alter_column("sleeper_rosters", "owner_id", type_=sa.String(length=32))
