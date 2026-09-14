"""Separate live availability from immutable quote history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0011_quote_availability'
down_revision = '0010_calibration_reports'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('quote_availability',
        sa.Column('kind', sa.String(8), primary_key=True),
        sa.Column('quote_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False))
    op.create_index('ix_quote_availability_source', 'quote_availability', ['source'])


def downgrade():
    op.drop_table('quote_availability')
