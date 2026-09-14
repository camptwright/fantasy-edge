"""sleeper_leagues.platform - this table now also holds ESPN Fantasy leagues.

The table/model names stay "sleeper_*" (avoiding a large, risky rename
across every consumer in src/api/main.py for a working production path -
same "keep historical naming stable" precedent as CLAUDE.md's own
deliberately non-contiguous constraint numbers). league_id disambiguates
rows across platforms on its own (Sleeper's are ~18-19 digit snowflake
ids; ESPN rows are stored as "espn:<numeric league id>" by
src/ingest/espn_fantasy.py) - this column exists for display/filtering,
not identity.

Revision ID: 0014_league_platform
Revises: 0013_result_repair
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_league_platform"
down_revision = "0013_result_repair"
branch_labels = None
depends_on = None


def upgrade():
    # Every row synced before this migration came from Sleeper - Sleeper
    # was the only platform integrated until now - so backfilling
    # 'sleeper' is an accurate value, not a placeholder.
    op.add_column(
        "sleeper_leagues",
        sa.Column("platform", sa.String(length=16), nullable=False, server_default="sleeper"),
    )


def downgrade():
    op.drop_column("sleeper_leagues", "platform")
