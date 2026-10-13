"""Neutral-site flag on games (bowls, CFP, international NFL games)."""
from alembic import op
import sqlalchemy as sa

revision = '0029_games_neutral_site'
down_revision = '0028_player_snap_counts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('games', sa.Column('neutral_site', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('games', 'neutral_site')
