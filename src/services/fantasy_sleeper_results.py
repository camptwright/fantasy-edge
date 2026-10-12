"""Reconciled component fallback; never interprets absent players as zero."""
import hashlib
import json
from datetime import datetime, timedelta
from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX, total
from src.services.fantasy_score_history import scoring_hash
from src.services.roster_stat_model import finite


def grade_components(record, game, archive, official):
    base={k:record[k] for k in ('id','league_id','position')}
    def blocked(reason):return {**base,'status':'component_result_withheld','result_blocker':reason}
    if game is None or game.status!='final':return blocked('awaiting_final')
    if str(game.id)!=record['game_id'] or game.week!=record['week']:return blocked('game_binding_mismatch')
    if not game.game_time or datetime.fromisoformat(record['captured_at'])>=game.game_time:return blocked('invalid_capture_time')
    if archive is None or official is None:return blocked('missing_result_evidence')
    a,o=archive.payload,official.payload
    if (type(a.get('schema_version')) is not int or a['schema_version']!=1
        or type(o.get('schema_version')) is not int or o['schema_version']!=1):
        return blocked('unsupported_result_schema')
    if not isinstance(o.get('game_ids'),list) or record['game_id'] not in o['game_ids']:
        return blocked('official_game_binding_mismatch')
    if (archive.league_id!=ARCHIVE_ID or archive.kind!=PREFIX+str(game.season)
        or archive.week!=record['week'] or official.league_id!=record['league_id']
        or official.week!=record['week'] or official.kind!='scored_history'
        or a.get('season')!=game.season or a.get('week')!=record['week']
        or o.get('season')!=str(game.season) or o.get('week')!=record['week']):
        return blocked('result_binding_mismatch')
    if min(archive.synced_at,official.synced_at)<game.game_time+timedelta(hours=24):return blocked('awaiting_final_snapshot')
    scoring=o.get('scoring_contract')
    if not isinstance(scoring,dict):return blocked('missing_scoring_contract')
    digest=hashlib.sha256(json.dumps(scoring,sort_keys=True).encode()).hexdigest()
    if (digest!=record['scoring_hash'] or scoring_hash(scoring)!=o.get('scoring_hash')
        or (record.get('scoring_contract_hash') and record['scoring_contract_hash']!=o['scoring_hash'])):
        return blocked('scoring_rules_mismatch')
    rows=a.get('players',{}); target=rows.get(record['player_id'])
    if not target or target.get('game_id')!=record['game_id']:return blocked('missing_exact_player_game')
    actual=total(target,scoring)
    if actual is None:return blocked('unsupported_or_incomplete_scoring')
    checks=[]
    for pid,row in rows.items():
        if row.get('position')!=target.get('position') or pid not in o.get('points',{}):continue
        value=total(row,scoring); point=o['points'][pid]
        checks.append(value is not None and finite(point) and abs(value-point)<1e-5)
    if len(checks)<8 or not all(checks):return blocked('insufficient_position_reconciliation')
    return {**base,'status':'graded_platform_total','actual':actual,
        'absolute_error':abs(actual-record['prediction']['points']),
        'result_source':'reconciled_sleeper_actual_components','reconciliation_samples':len(checks),
        'result_observed_at':archive.synced_at.isoformat()}


def recover_lineup_points(record, official, archive, games):
    """Enrich a grading copy only; never alter frozen lineups or official rows."""
    points=dict(official.payload.get('points',{})); recovered={}; blocked={}
    evidence=record.get('lineup_experiment',{})
    if evidence.get('scoring_hash')!=official.payload.get('scoring_hash'):
        return points, {'status':'scoring_rules_mismatch','recovered':{}}
    sim=evidence.get('simulation',{})
    ids=set(record['lineups']['opponent_starters'])
    for name in ('current','candidate'):ids.update(sim.get(name,{}).get('player_ids',[]))
    allowed={g['id'] for g in record['lineups']['games']}
    scoring=official.payload.get('scoring_contract',{})
    for pid in sorted(ids-set(points)):
        row=archive.payload.get('players',{}).get(pid,{}) if archive else {}
        gid=row.get('game_id')
        if gid not in allowed:
            blocked[pid]='missing_frozen_game_binding';continue
        item={'id':record['id'],'league_id':record['league_id'],'position':row.get('position'),
            'player_id':pid,'week':record['week'],'game_id':gid,'captured_at':record['captured_at'],
            'scoring_hash':hashlib.sha256(json.dumps(scoring,sort_keys=True).encode()).hexdigest(),
            'scoring_contract_hash':evidence['scoring_hash'],'prediction':{'points':0}}
        result=grade_components(item,games.get(gid),archive,official)
        if result['status']=='graded_platform_total':
            points[pid]=result['actual']
            recovered[pid]={k:result[k] for k in ('actual','result_source','reconciliation_samples','result_observed_at')}
        else:blocked[pid]=result['result_blocker']
    return points, {'status':'checked','recovered':recovered,'blocked':blocked}
