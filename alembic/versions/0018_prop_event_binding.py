"""Persist exact provider-event corroboration without rewriting quote history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0018_prop_event_binding'
down_revision = '0017_betting_ledger'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('quote_availability', sa.Column('event_binding', JSONB(), nullable=True))


def downgrade():
    op.drop_column('quote_availability', 'event_binding')
