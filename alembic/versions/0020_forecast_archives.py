"""Durable content-addressed general forecast and grade evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0020_forecast_archives'
down_revision = '0019_model_evidence'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('forecast_archives',
        sa.Column('digest', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(16), primary_key=True),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table('forecast_archives')
