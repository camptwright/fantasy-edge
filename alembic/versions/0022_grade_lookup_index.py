"""Avoid deserializing grading history to serve the newest report."""
from alembic import op
revision='0022_grade_lookup_index'
down_revision='0021_forecast_json_precision'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("CREATE INDEX ix_forecast_archives_graded_at ON forecast_archives ((payload->>'graded_at') DESC, digest DESC) WHERE kind='grading'")

def downgrade():
    op.drop_index('ix_forecast_archives_graded_at',table_name='forecast_archives')
