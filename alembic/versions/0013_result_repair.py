"""Durable outcome retry cursors and provider correction audit."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0013_result_repair'
down_revision = '0012_recommendation_evidence'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('result_sync_states',
        sa.Column('game_id', UUID(as_uuid=True), sa.ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('provider', sa.String(32), primary_key=True),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('detail', sa.Text()))
    op.create_index('ix_result_sync_states_next_attempt_at', 'result_sync_states', ['next_attempt_at'])
    op.create_table('result_corrections',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('stat_id', UUID(as_uuid=True), sa.ForeignKey('player_game_stats.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('event_id', sa.String(64), nullable=False),
        sa.Column('old_value', sa.Float(), nullable=False), sa.Column('new_value', sa.Float(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('first_payload_hash', sa.String(64), nullable=False),
        sa.Column('last_payload_hash', sa.String(64), nullable=False))
    op.create_index('ix_result_corrections_stat_id', 'result_corrections', ['stat_id'])
    op.create_index('ix_result_corrections_status', 'result_corrections', ['status'])


def downgrade():
    op.drop_table('result_corrections')
    op.drop_table('result_sync_states')
