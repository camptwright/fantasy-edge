"""Transactional invalidation for background fantasy read models."""
from alembic import op
import sqlalchemy as sa
revision='0025_fantasy_input_revision'
down_revision='0024_derived_checkpoints'
branch_labels=None
depends_on=None

TABLES=('sleeper_leagues','sleeper_rosters','sleeper_league_snapshots','games',
        'player_game_stats','result_corrections','players','player_external_ids','teams')


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table('fantasy_input_revision',sa.Column('id',sa.Integer(),primary_key=True),
                    sa.Column('revision',sa.BigInteger(),nullable=False))
    op.execute('INSERT INTO fantasy_input_revision VALUES (1,0)')
    op.execute('''CREATE FUNCTION invalidate_fantasy_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1; RETURN NULL; END $$''')
    for table in TABLES:
        op.execute(f'CREATE TRIGGER invalidate_fantasy_inputs AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_fantasy_inputs()')


def downgrade():
    for table in TABLES:op.execute(f'DROP TRIGGER invalidate_fantasy_inputs ON {table}')
    op.execute('DROP FUNCTION invalidate_fantasy_inputs()')
    op.drop_table('fantasy_input_revision')
