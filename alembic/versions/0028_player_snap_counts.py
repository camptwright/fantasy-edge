"""Per player-game offensive snap counts for usage-share projections."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0028_player_snap_counts'
down_revision = '0027_fantasy_scope_revisions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'player_snap_counts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('player_id', UUID(as_uuid=True), sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('game_id', UUID(as_uuid=True), sa.ForeignKey('games.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('team_id', UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('offense_snaps', sa.Integer(), nullable=False),
        sa.Column('offense_pct', sa.Float(), nullable=False),
        sa.Column('st_snaps', sa.Integer()),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('player_id', 'game_id', 'source', name='uq_player_snap_count'),
    )
    op.create_index('ix_player_snap_counts_game_team', 'player_snap_counts', ['game_id', 'team_id'])


def downgrade():
    op.drop_index('ix_player_snap_counts_game_team', table_name='player_snap_counts')
    op.drop_table('player_snap_counts')
