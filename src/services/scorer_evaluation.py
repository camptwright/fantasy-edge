"""Evaluate frozen joint scorer distributions including OTHER and NONE.

No fitting, rate adjustment, bookmaker settlement or serving approval. Input
predictions must precede kickoff; outputs remain research scoring metrics.
"""
import math
from statistics import fmean
from datetime import datetime


def timestamp(value):
    parsed=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone-aware evidence timestamps required')
    return parsed


def distribution_score(probabilities, outcome):
    if not {'__other__','__none__'} <= set(probabilities) or outcome not in probabilities:
        raise ValueError('Complete frozen outcome universe required')
    values=list(probabilities.values())
    if any(isinstance(p,bool) or not isinstance(p,(float,int)) or not math.isfinite(p) or not 0<=p<=1 for p in values) or not math.isclose(sum(values),1,abs_tol=1e-8):
        raise ValueError('Normalized finite probability distribution required')
    return {'multiclass_brier':sum((p-int(k==outcome))**2 for k,p in probabilities.items()),
            'log_loss':-math.log(max(probabilities[outcome],1e-15)),
            'zero_probability_outcome':probabilities[outcome]==0}


def evaluate(records):
    scores,excluded,seen=[],[],set()
    for row in records:
        key=(row['game_id'],row['market'])
        if key in seen:
            raise ValueError('Duplicate game/market evaluation unit')
        seen.add(key)
        captured,kickoff,available=(timestamp(row[k]) for k in ('captured_at','kickoff','training_available_at'))
        if (captured>=kickoff or available>captured
            or not row['validated_final'] or row['pending_correction']):
            excluded.append({'game_id':row['game_id'],'reason':'timing_or_result_evidence'})
            continue
        if set(row['baseline'])!=set(row['candidate']):
            raise ValueError('Baseline and candidate must share a frozen universe')
        scores.append({'game_id':row['game_id'],'market':row['market'],
            'baseline':distribution_score(row['baseline'],row['outcome']),
            'candidate':distribution_score(row['candidate'],row['outcome'])})
    metrics=[]
    for market in sorted({r['market'] for r in scores}):
        group=[r for r in scores if r['market']==market]
        metrics.append({'market':market,'games':len(group),**{metric+'_delta':fmean(r['candidate'][metric]-r['baseline'][metric] for r in group) for metric in ('multiclass_brier','log_loss')}})
    return {'scores':scores,'metrics':metrics,'excluded':excluded,'serving_enabled':False,
            'scope':'paired_regulation_scorer_research_not_bookmaker_grading'}
