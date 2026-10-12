"""Auditable, explicitly approved model selection and baseline rollback."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
revision='0023_model_deployments'
down_revision='0022_grade_lookup_index'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('model_deployments',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('scope',sa.String(32),nullable=False),
        sa.Column('artifact_version',sa.String(64),sa.ForeignKey('model_artifacts.version',ondelete='RESTRICT')),
        sa.Column('review_id',UUID(as_uuid=True),sa.ForeignKey('model_review_evidence.id',ondelete='RESTRICT')),
        sa.Column('actor',sa.String(128),nullable=False),sa.Column('reason',sa.Text(),nullable=False))
    op.create_index('ix_model_deployments_scope','model_deployments',['scope'])

def downgrade():
    op.drop_table('model_deployments')
