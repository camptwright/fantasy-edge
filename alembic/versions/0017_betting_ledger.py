"""Append-only singles, settlement/closing evidence and explicit risk policies."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0017_betting_ledger'
down_revision = '0016_roster_team_name'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ledger_bets',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_id', sa.String(80), nullable=False, unique=True),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('stake', sa.Numeric(14, 2), nullable=False),
        sa.Column('placed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('game_id', pg.UUID(as_uuid=True), sa.ForeignKey('games.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('terms', pg.JSONB(), nullable=False),
        sa.CheckConstraint('stake > 0', name='ledger_positive_stake'))
    op.create_index('ix_ledger_bets_game_id', 'ledger_bets', ['game_id'])
    op.create_table('ledger_events',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_id', sa.String(80), nullable=False, unique=True),
        sa.Column('bet_id', pg.UUID(as_uuid=True), sa.ForeignKey('ledger_bets.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('payload', pg.JSONB(), nullable=False))
    op.create_index('ix_ledger_events_bet_id', 'ledger_events', ['bet_id'])
    op.create_table('ledger_policies',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('limits', pg.JSONB(), nullable=False))


def downgrade():
    op.drop_table('ledger_policies')
    op.drop_table('ledger_events')
    op.drop_table('ledger_bets')
