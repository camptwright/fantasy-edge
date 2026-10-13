"""IR and taxi player lists on rosters, so waiver advice never drops them."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0030_roster_reserve'
down_revision = '0029_games_neutral_site'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sleeper_rosters', sa.Column('reserve', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('sleeper_rosters', sa.Column('taxi', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column('sleeper_rosters', 'taxi')
    op.drop_column('sleeper_rosters', 'reserve')
