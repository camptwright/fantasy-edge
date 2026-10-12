"""Bind existing checkpoints to shared and league input revisions."""
from alembic import op
import sqlalchemy as sa

revision = '0027_fantasy_scope_revisions'
down_revision = '0026_fantasy_invalidation'
branch_labels = None
depends_on = None

LEGACY_BUMP = 'UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1;'
SHARED_BUMP = """INSERT INTO fantasy_scope_revisions(scope, revision) VALUES ('shared', 1)
            ON CONFLICT(scope) DO UPDATE SET revision=fantasy_scope_revisions.revision+1;"""
SCOPED_BUMP = """IF TG_TABLE_NAME IN ('sleeper_leagues','sleeper_rosters','sleeper_league_snapshots') THEN
              EXECUTE 'SELECT array_agg(DISTINCT COALESCE(''league:'' || (d.r->>''league_id''), ''shared'')) FROM (' || delta_sql || ') d' INTO scopes;
              INSERT INTO fantasy_scope_revisions(scope, revision)
                SELECT s, 1 FROM unnest(scopes) s ORDER BY s
                ON CONFLICT(scope) DO UPDATE SET revision=fantasy_scope_revisions.revision+1;
            ELSE
              """ + SHARED_BUMP + """
            END IF;"""


def trigger_definition():
    return op.get_bind().scalar(sa.text("SELECT pg_get_functiondef('invalidate_fantasy_inputs()'::regprocedure)"))


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Drain writes using the old function before enabling scoped evidence.
    # Otherwise an in-flight old trigger could commit without a scoped bump.
    op.execute('LOCK TABLE derived_checkpoints, games, player_external_ids, player_game_stats, '
               'players, result_corrections, sleeper_league_snapshots, sleeper_leagues, '
               'sleeper_rosters, teams IN SHARE ROW EXCLUSIVE MODE')
    op.create_table('fantasy_scope_revisions', sa.Column('scope', sa.Text(), primary_key=True),
                    sa.Column('revision', sa.BigInteger(), nullable=False))
    op.create_table('fantasy_checkpoint_scopes',
        sa.Column('name', sa.String(128), sa.ForeignKey('derived_checkpoints.name', ondelete='CASCADE'), primary_key=True),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('legacy_revision', sa.BigInteger(), nullable=False),
        sa.Column('shared_revision', sa.BigInteger(), nullable=False),
        sa.Column('league_revision', sa.BigInteger(), nullable=False))
    # A writer whose repeatable-read snapshot predates migration sees 0 instead
    # of this epoch. Such a checkpoint must not gain current scoped evidence.
    op.execute("INSERT INTO fantasy_scope_revisions(scope, revision) VALUES ('shared',1)")
    # Extend the exact deployed 0026 function, retaining its change/sport filters.
    # Fail closed if its expected structure is not present; DDL is transactional.
    definition = trigger_definition()
    if definition.count(LEGACY_BUMP) != 2 or definition.count('changed boolean;') != 1:
        raise RuntimeError('Unexpected invalidation function; migration aborted')
    definition = definition.replace('changed boolean;', 'changed boolean; scopes text[];')
    definition = definition.replace(LEGACY_BUMP, LEGACY_BUMP + '\n' + SHARED_BUMP, 1)
    at = definition.rfind(LEGACY_BUMP)
    definition = definition[:at] + definition[at:].replace(LEGACY_BUMP, LEGACY_BUMP + '\n' + SCOPED_BUMP, 1)
    op.execute(definition)
    op.execute("""CREATE FUNCTION bind_fantasy_checkpoint_scopes() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE current_revision bigint; shared bigint; league bigint;
      BEGIN
        IF NEW.name NOT LIKE 'fantasy:%' THEN RETURN NULL; END IF;
        DELETE FROM fantasy_checkpoint_scopes WHERE name=NEW.name;
        SELECT revision INTO current_revision FROM fantasy_input_revision WHERE id=1;
        -- Only bind a checkpoint made from this transaction's source snapshot.
        -- Old/stale externally supplied payloads cannot acquire fresh revisions.
        IF NEW.payload->>'revision' IS DISTINCT FROM current_revision::text THEN RETURN NULL; END IF;
        SELECT COALESCE((SELECT revision FROM fantasy_scope_revisions WHERE scope='shared'),0) INTO shared;
        SELECT COALESCE((SELECT revision FROM fantasy_scope_revisions WHERE scope='league:' || substring(NEW.name FROM 9)),0) INTO league;
        INSERT INTO fantasy_checkpoint_scopes(name,digest,legacy_revision,shared_revision,league_revision)
          VALUES(NEW.name,NEW.digest,current_revision,shared,league);
        RETURN NULL;
      END $$""")
    op.execute('CREATE TRIGGER bind_fantasy_checkpoint_scopes AFTER INSERT OR UPDATE ON derived_checkpoints '
               'FOR EACH ROW EXECUTE FUNCTION bind_fantasy_checkpoint_scopes()')
    # Existing checkpoints deliberately remain unbound; the next scheduled
    # refresh establishes evidence without reconstructing an old snapshot.


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    definition = trigger_definition()
    definition = definition.replace(LEGACY_BUMP + '\n' + SCOPED_BUMP, LEGACY_BUMP)
    definition = definition.replace(LEGACY_BUMP + '\n' + SHARED_BUMP, LEGACY_BUMP)
    definition = definition.replace('changed boolean; scopes text[];', 'changed boolean;')
    if 'fantasy_scope_revisions' in definition:
        raise RuntimeError('Unexpected scoped trigger definition; rollback aborted')
    op.execute(definition)
    op.execute('DROP TRIGGER bind_fantasy_checkpoint_scopes ON derived_checkpoints')
    op.execute('DROP FUNCTION bind_fantasy_checkpoint_scopes()')
    op.drop_table('fantasy_checkpoint_scopes')
    op.drop_table('fantasy_scope_revisions')
    op.execute(LEGACY_BUMP)
