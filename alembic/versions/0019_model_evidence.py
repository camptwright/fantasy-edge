"""Durable artifact, frozen forecast and promotion-review evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = '0019_model_evidence'
down_revision = '0018_prop_event_binding'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_artifacts', sa.Column('artifact_payload', JSONB(), nullable=True))
    op.add_column('model_predictions', sa.Column('evidence', JSONB(), nullable=True))
    op.create_table('model_review_evidence',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('artifact_version', sa.String(64), sa.ForeignKey('model_artifacts.version', ondelete='RESTRICT'), nullable=False),
        sa.Column('report', JSONB(), nullable=False))
    op.create_index('ix_model_review_evidence_artifact_version', 'model_review_evidence', ['artifact_version'])


def downgrade():
    op.drop_table('model_review_evidence')
    op.drop_column('model_predictions', 'evidence')
    op.drop_column('model_artifacts', 'artifact_payload')
