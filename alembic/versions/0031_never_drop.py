"""Owner never-drop list per fantasy league."""
from alembic import op
import sqlalchemy as sa

revision = '0031_never_drop'
down_revision = '0030_roster_reserve'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fantasy_never_drop',
                    sa.Column('league_id', sa.String(32), primary_key=True),
                    sa.Column('player_id', sa.String(80), primary_key=True),
                    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    op.drop_table('fantasy_never_drop')
