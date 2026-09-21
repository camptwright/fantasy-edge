"""Independent kicker research recipe. Never automatically promotes serving."""
from collections import defaultdict
from statistics import fmean
import json
from pathlib import Path
from config.settings import get_settings
from src.services.roster_stat_model import finite

KICKING = {
    'xpm': ('fantasy_pat_made',), 'xpmiss': ('fantasy_pat_missed',),
    'fgmiss': ('fantasy_fg_missed',),
    'fgm_0_19': ('fantasy_fg_0_19',), 'fgm_20_29': ('fantasy_fg_20_29',),
    'fgm_30_39': ('fantasy_fg_30_39',), 'fgm_40_49': ('fantasy_fg_40_49',),
    'fgm_50_59': ('fantasy_fg_50_59',), 'fgm_60p': ('fantasy_fg_60_plus',),
    'fgm_50p': ('fantasy_fg_50_59','fantasy_fg_60_plus'),
    'espn_fg_missed': ('fantasy_fg_missed',), 'espn_pat_made': ('fantasy_pat_made',),
    'espn_fg_under_40': ('fantasy_fg_under_40',), 'espn_fg_40_49': ('fantasy_fg_40_49',),
    'espn_fg_50_59': ('fantasy_fg_50_59',), 'espn_fg_60_plus': ('fantasy_fg_60_plus',),
}
RECIPE='kicker_recency_blend_v1'


def latest(league_id):
    paths=sorted((Path(get_settings().raw_archive_dir)/'fantasy-specialists'/'reports').glob('*.json'))
    if not paths:return {'status':'not_evaluated','serving_promoted':False}
    try:
        report=json.loads(paths[-1].read_text())
        return {**report,'kicker':[r for r in report['kicker'] if r['league_id']==league_id]}
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'invalid_evaluation_archive','serving_promoted':False}


def weights(scoring):
    result={}; missing=[]
    for key,value in scoring.items():
        if not finite(value) or not value: continue
        if key in KICKING:
            for field in KICKING[key]: result[field]=result.get(field,0)+float(value)
        elif key.startswith(('fg','xp','espn_')):
            missing.append(key)
    return result,missing


def candidate(rows,scoring):
    mapping,missing=weights(scoring)
    complete=sorted((r for r in rows if mapping and all(finite(r['values'].get(k)) for k in mapping)),
                    key=lambda r:(r['time'],r['game_id']))[-20:]
    base={'recipe':RECIPE,'serving_promoted':False,'games':len(complete),
          'missing_scoring_keys':missing,'conditional_on_playing':True,
          'scope':'kicking_components_only_not_full_fantasy_ros', 'per_game':None,
          'modelled_kicking_per_game':None}
    if missing or len(complete)<8:return {**base,'status':'insufficient_kicking_evidence'}
    totals=[sum(r['values'][k]*v for k,v in mapping.items()) for r in complete]
    baseline=fmean(totals)
    return {**base,'status':'research_candidate','baseline':baseline,
            'modelled_kicking_per_game':.75*baseline+.25*fmean(totals[-4:])}


def holdout(rows,scoring,season):
    """One final-season holdout, ordered by week; every prediction uses prior rows only.

    Retrospective corrected outcomes are not prospective source availability.
    MAE is per game, not evidence validating full ROS totals.
    """
    keys=[(r['player_id'],r['game_id']) for r in rows]
    if len(keys)!=len(set(keys)): raise ValueError('duplicate player game')
    histories=defaultdict(list); evaluated=[]; excluded=0
    mapping,gaps=weights(scoring)
    for row in sorted(rows,key=lambda r:(r['season'],r['week'],r['player_id'])):
        prior=histories[row['player_id']]
        if row['season']==season:
            forecast=candidate(prior,scoring)
            if forecast['status']=='research_candidate' and all(finite(row['values'].get(k)) for k in mapping):
                actual=sum(row['values'][k]*v for k,v in mapping.items())
                evaluated.append({'player_id':row['player_id'],'week':row['week'],
                    'baseline_error':abs(actual-forecast['baseline']),
                    'candidate_error':abs(actual-forecast['modelled_kicking_per_game'])})
            else: excluded+=1
        if row['season']<=season: prior.append(row)
    improved=bool(evaluated) and fmean(r['candidate_error']-r['baseline_error'] for r in evaluated)<0
    return {'recipe':RECIPE,'holdout_season':season,'n':len(evaluated),
            'evaluation_decision':'needs_independent_prospective_validation' if improved else 'retain_baseline',
            'players':len({r['player_id'] for r in evaluated}), 'excluded':excluded,
            'baseline_mae':fmean(r['baseline_error'] for r in evaluated) if evaluated else None,
            'candidate_mae':fmean(r['candidate_error'] for r in evaluated) if evaluated else None,
            'missing_scoring_keys':gaps,'serving_promoted':False,
            'scope':'retrospective_per_game_kicking_components_not_full_ros',
            'limitations':['Corrected archive, not point-in-time provider history.',
                          'Participation and non-kicking scoring are not modeled.',
                          'No automatic promotion from this comparison.']}
