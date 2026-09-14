"""Retain quote identities so cached narratives can be invalidated safely."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = '0012_recommendation_evidence'
down_revision = '0011_quote_availability'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('recommendation_snapshots', sa.Column('quote_ids', ARRAY(sa.String(36)), nullable=True))


def downgrade():
    op.drop_column('recommendation_snapshots', 'quote_ids')
