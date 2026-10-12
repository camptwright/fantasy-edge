"""Preserve JSON numeric representation for content-addressed evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON,JSONB
revision='0021_forecast_json_precision'
down_revision='0020_forecast_archives'
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column('forecast_archives','payload',type_=JSON(),postgresql_using='payload::json')

def downgrade():
    op.alter_column('forecast_archives','payload',type_=JSONB(),postgresql_using='payload::jsonb')
