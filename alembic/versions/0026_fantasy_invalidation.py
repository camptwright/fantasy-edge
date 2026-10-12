"""Invalidate NFL fantasy checkpoints only for relevant changed rows.

Preserves the existing revision protocol, so old readers and writers remain
compatible. No schema or forecast identity changes are required for rollout.
"""
from alembic import op

revision = '0026_fantasy_invalidation'
down_revision = '0025_fantasy_input_revision'
branch_labels = None
depends_on = None

TABLES = ('sleeper_leagues', 'sleeper_rosters', 'sleeper_league_snapshots',
          'games', 'player_game_stats', 'result_corrections', 'players',
          'player_external_ids', 'teams')


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in TABLES:
        op.execute(f'DROP TRIGGER invalidate_fantasy_inputs ON {table}')
    op.execute("""CREATE OR REPLACE FUNCTION invalidate_fantasy_inputs()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE delta_sql text; filter_sql text; changed boolean;
        BEGIN
          IF TG_OP = 'TRUNCATE' THEN
            UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1;
            RETURN NULL;
          END IF;
          IF TG_OP = 'INSERT' THEN
            delta_sql := 'SELECT to_jsonb(n) AS r FROM new_rows n';
          ELSIF TG_OP = 'DELETE' THEN
            delta_sql := 'SELECT to_jsonb(o) AS r FROM old_rows o';
          ELSE
            -- Full-row equality includes freshness timestamps and scoring JSON.
            -- Include both sides: changing a sport or FK must invalidate the old
            -- domain as well as the new domain. Empty/no-op writes do nothing.
            delta_sql := '(SELECT to_jsonb(n) AS r FROM new_rows n EXCEPT SELECT to_jsonb(o) FROM old_rows o)
                          UNION ALL
                          (SELECT to_jsonb(o) AS r FROM old_rows o EXCEPT SELECT to_jsonb(n) FROM new_rows n)';
          END IF;
          IF TG_TABLE_NAME IN ('games','players','teams','sleeper_leagues') THEN
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d
                           WHERE d.r->>''sport'' IS NULL OR d.r->>''sport'' = ''nfl''';
          ELSIF TG_TABLE_NAME IN ('sleeper_rosters','sleeper_league_snapshots') THEN
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d
                           LEFT JOIN sleeper_leagues l ON l.league_id=d.r->>''league_id''
                           WHERE l.sport IS NULL OR l.sport=''nfl''';
          ELSIF TG_TABLE_NAME = 'player_game_stats' THEN
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d
                           LEFT JOIN games g ON g.id=(d.r->>''game_id'')::uuid
                           WHERE g.sport IS NULL OR g.sport=''nfl''';
          ELSIF TG_TABLE_NAME = 'result_corrections' THEN
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d
                           LEFT JOIN player_game_stats s ON s.id=(d.r->>''stat_id'')::uuid
                           LEFT JOIN games g ON g.id=s.game_id
                           WHERE g.sport IS NULL OR g.sport=''nfl''';
          ELSIF TG_TABLE_NAME = 'player_external_ids' THEN
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d
                           LEFT JOIN players p ON p.id=(d.r->>''player_id'')::uuid
                           WHERE p.sport IS NULL OR p.sport=''nfl''';
          ELSE
            -- Unknown source domains fail closed rather than preserving cache.
            filter_sql := 'SELECT 1 FROM (' || delta_sql || ') d';
          END IF;
          EXECUTE 'SELECT EXISTS (' || filter_sql || ')' INTO changed;
          IF changed THEN
            UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1;
          END IF;
          RETURN NULL;
        END $$""")
    for table in TABLES:
        for event, transition in (
            ('INSERT', 'REFERENCING NEW TABLE AS new_rows'),
            ('UPDATE', 'REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows'),
            ('DELETE', 'REFERENCING OLD TABLE AS old_rows'),
            ('TRUNCATE', ''),
        ):
            op.execute(f'CREATE TRIGGER invalidate_fantasy_{event.lower()} AFTER {event} ON {table} '
                       f'{transition} FOR EACH STATEMENT EXECUTE FUNCTION invalidate_fantasy_inputs()')
    # Force one refresh on migration; never reuse a pre-migration checkpoint.
    op.execute('UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1')


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in TABLES:
        for event in ('insert', 'update', 'delete', 'truncate'):
            op.execute(f'DROP TRIGGER invalidate_fantasy_{event} ON {table}')
    op.execute('''CREATE OR REPLACE FUNCTION invalidate_fantasy_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1; RETURN NULL; END $$''')
    for table in TABLES:
        op.execute(f'CREATE TRIGGER invalidate_fantasy_inputs AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} '
                   'FOR EACH STATEMENT EXECUTE FUNCTION invalidate_fantasy_inputs()')
    op.execute('UPDATE fantasy_input_revision SET revision=revision+1 WHERE id=1')
