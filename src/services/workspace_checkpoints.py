"""League-scoped preview reads of unchanged legacy background checkpoints.

Kept outside the fantasy model recipe glob: presentation/cache delivery is not
prediction math. No provider access, generation, refresh dispatch, or writes.
"""
from datetime import datetime, timezone
from sqlalchemy import text
from src.services.fantasy_read_model import recipe
from src.services.forecast_evidence import digest
from src.services.workspace_player_evidence import bind_defense_identities


async def read(db, league_id):
    # One statement binds payload, digest, stored revisions, and current inputs.
    row = (await db.execute(text('''
        SELECT c.payload, c.digest, b.digest AS bound_digest, b.legacy_revision,
               b.shared_revision, b.league_revision,
               (SELECT revision FROM fantasy_input_revision WHERE id=1) AS current_legacy,
               COALESCE((SELECT revision FROM fantasy_scope_revisions WHERE scope='shared'),0) AS current_shared,
               COALESCE((SELECT revision FROM fantasy_scope_revisions WHERE scope=:scope),0) AS current_league,
               (SELECT jsonb_agg(jsonb_build_object('id',id,'sport',sport,'abbr',nflverse_abbr,'espn_id',espn_id))
                FROM teams WHERE sport='nfl') AS canonical_teams,
               l.synced_at AS espn_observed_at,
               CASE WHEN l.platform='espn' AND l.sport='nfl'
                    AND jsonb_typeof(l.raw->'defense_identities')='array'
                    THEN l.raw->'defense_identities'
               END AS espn_defenses
        FROM derived_checkpoints c
        LEFT JOIN fantasy_checkpoint_scopes b ON b.name=c.name
        LEFT JOIN sleeper_leagues l ON l.league_id=:league_id
        WHERE c.name=:name
    '''), {'scope': 'league:' + league_id, 'name': 'fantasy:' + league_id, 'league_id':league_id})).mappings().first()
    if row is None:
        return None
    payload = row['payload']
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
        return None
    if row['bound_digest'] is None:
        # Transitional fallback is conservative; no scope evidence is invented.
        if payload.get('revision') != row['current_legacy']:
            return None
        mode = 'legacy_global'
    else:
        if (row['bound_digest'] != row['digest'] or
            payload.get('revision') != row['legacy_revision'] or
            row['shared_revision'] != row['current_shared'] or
            row['league_revision'] != row['current_league']):
            return None
        mode = 'league_and_shared_nfl'
    if payload.get('recipe') != recipe() or digest(payload) != row['digest']:
        return None
    now = datetime.now(timezone.utc)
    try:
        generated = datetime.fromisoformat(payload['generated_at'])
        expires = datetime.fromisoformat(payload['expires_at'])
        valid_time = generated <= now < expires
    except (KeyError, TypeError, ValueError):
        return None
    if not valid_time:
        return None
    observed = row.get('espn_observed_at')
    espn_defenses = (row.get('espn_defenses') or []) if observed and observed <= generated and 0 <= (now-observed).total_seconds() <= 21600 else []
    return {**bind_defense_identities(payload['data'], row.get('canonical_teams') or [], espn_defenses), 'read_model': {
        'source': 'background_checkpoint', 'generated_at': payload['generated_at'],
        'expires_at': payload['expires_at'], 'input_revision': payload['revision'],
        'invalidation_scope': mode}}
