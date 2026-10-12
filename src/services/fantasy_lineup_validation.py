"""Grade frozen lineup win probabilities; never infer unavailable player totals."""
from src.services.roster_stat_model import finite
from src.services.fantasy_score_history import scoring_hash


def frozen(lab):
    sim=lab.get('lineup_simulation',{})
    if sim.get('status')!='estimated_research':return None
    return {'simulation':sim,'scoring_hash':lab.get('scoring_contract_hash') or scoring_hash(lab['scoring_settings']),
        'player_evidence':[{k:p.get(k) for k in ('player_id','weekly_evidence','score_samples',
            'distribution_source','distribution_evidence','game_availability')} for p in lab['players']
            if p['player_id'] in set(sim['current']['player_ids']+sim['candidate']['player_ids']+
                                   list(map(str,lab['validation_lineups']['opponent_starters'])))],
        'scope':'frozen_lineups_not_subsequent_platform_lineup_changes','serving_promoted':False}


def grade(record,points):
    evidence=record.get('lineup_experiment')
    if not evidence:return {'status':'legacy_no_simulation'}
    opponent=list(map(str,record['lineups']['opponent_starters']))
    result={'status':'graded','serving_promoted':False}
    for name in ('current','candidate'):
        prediction=evidence['simulation'][name]
        ids=prediction['player_ids']
        if not ids or not opponent or any(not finite(points.get(pid)) for pid in ids+opponent):
            return {'status':'missing_player_points'}
        margin=sum(points[p] for p in ids)-sum(points[p] for p in opponent)
        probability=prediction['estimated_win_probability']
        if not finite(probability) or not 0<=probability<=1:return {'status':'invalid_probability'}
        # Win excludes ties, consistent with the simulator. Ties are explicit.
        outcome=int(margin>0)
        result[name]={'actual_margin':margin,'won':bool(outcome),'tied':margin==0,
            'win_probability':probability,'brier':(probability-outcome)**2,
            'coinflip_brier':(.5-outcome)**2}
    return result
