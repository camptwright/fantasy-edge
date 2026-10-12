"""Replaceable, integrity-checked derived checkpoints; not source evidence."""
from alembic import op
import sqlalchemy as sa
revision='0024_derived_checkpoints'
down_revision='0023_model_deployments'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('derived_checkpoints',
        sa.Column('name',sa.String(128),primary_key=True),
        sa.Column('digest',sa.String(64),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))


def downgrade():
    op.drop_table('derived_checkpoints')
