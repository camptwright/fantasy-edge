"""Grade frozen modeled components from reconciled played-game evidence only."""
import hashlib
import json
from src.services.fantasy_decision_models import CORE
from src.services.fantasy_sleeper_results import grade_components


def recover(record, game, archive, official, *, identity_matches=False, existing_values=None):
    def blocked(reason):return {'status':'withheld','reason':reason}
    if not identity_matches or record['league_id'].startswith('espn:'):
        return blocked('unverified_platform_identity')
    if game is None or archive is None or official is None:return blocked('missing_result_evidence')
    pid=record.get('platform_player_id')
    row=archive.payload.get('players',{}).get(pid,{})
    scoring=record.get('scoring_settings',{})
    proxy={'id':record['id'],'league_id':record['league_id'],'position':row.get('position'),
        'player_id':pid,'week':game.week,'game_id':record['game_id'],
        'captured_at':record['captured_at'],
        'scoring_hash':hashlib.sha256(json.dumps(scoring,sort_keys=True).encode()).hexdigest(),
        'prediction':{'points':0}}
    verified=grade_components(proxy,game,archive,official)
    if verified['status']!='graded_platform_total':
        return blocked(verified['result_blocker'])
    inverse={}
    for key,stat in CORE.items():inverse.setdefault(stat,[]).append(key)
    values={}
    for stat,weight in record['prediction']['scoring_weights'].items():
        keys=[key for key in inverse.get(stat,[]) if scoring.get(key)==weight]
        if len(keys)!=1:return blocked('frozen_component_mapping_mismatch')
        # grade_components established gp=1, bounded scoring vocabulary, exact
        # event and position-level agreement with official league totals.
        values[stat]=row['stats'].get(keys[0],0)
        if stat in (existing_values or {}) and existing_values[stat]!=values[stat]:
            return blocked('conflicting_existing_component')
    from src.services.fantasy_prospective import grade
    result=grade(record,game,values)
    return {**result,'result_source':'reconciled_sleeper_played_components',
            'result_observed_at':verified['result_observed_at'],
            'reconciliation_samples':verified['reconciliation_samples']}
