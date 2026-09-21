"""Small, transparent NFL stat lab. No production pricing or lineup changes."""
import math
import statistics

STATS = {'QB': ['passing_yards', 'passing_touchdowns', 'passing_interceptions', 'rushing_yards'],
         'RB': ['rushing_yards', 'rushing_attempts', 'receptions', 'receiving_yards'],
         'WR': ['targets', 'receptions', 'receiving_yards'],
         'TE': ['targets', 'receptions', 'receiving_yards']}
USAGE = {'passing_yards': 'passing_attempts', 'rushing_yards': 'rushing_attempts',
         'receiving_yards': 'targets', 'receptions': 'targets'}
RECIPE = 'roster_stat_lab_v1_min8_window20_usage5_blend50'


def workload_candidate(rows, stat, baseline):
    """Frozen shrinkage recipe; paired games only, never proxy missing targets."""
    usage=USAGE.get(stat)
    paired=[r for r in rows if usage and finite(r['values'].get(usage)) and r['values'][usage]>=0]
    if len(paired)<8 or sum(r['values'][usage] for r in paired)<=0:
        return {'status':'missing_opportunity_history','recipe':'workload_shrink8_v1'}
    historical=statistics.fmean(r['values'][usage] for r in paired)
    recent=statistics.fmean(r['values'][usage] for r in paired[-5:])
    projected_usage=(8*historical+5*recent)/13
    rate=sum(r['values'][stat] for r in paired)/sum(r['values'][usage] for r in paired)
    sigma=statistics.pstdev(r['values'][stat] for r in rows)
    mean=max(baseline-sigma,min(baseline+sigma,projected_usage*rate))
    return {'status':'ready','recipe':'workload_shrink8_v1','mean':mean,'usage_stat':usage,
            'expected_usage':projected_usage,'historical_usage':historical,'recent_usage':recent,
            'rate':rate,'paired_games':len(paired),'conditional_on_playing':True}


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def estimate(rows, stat):
    rows = [r for r in rows if finite(r['values'].get(stat))][-20:]
    if len(rows) < 8:
        return {'status': 'insufficient_history', 'games': len(rows)}
    values = [r['values'][stat] for r in rows]
    baseline = statistics.fmean(values)
    candidate, reason, opportunity = baseline, 'baseline_only', None
    usage = USAGE.get(stat)
    paired = [r for r in rows if finite(r['values'].get(usage)) and r['values'][usage] >= 0] if usage else []
    if len(paired) >= 8 and sum(r['values'][usage] for r in paired) > 0:
        recent_usage = statistics.fmean(r['values'][usage] for r in paired[-5:])
        rate = sum(r['values'][stat] for r in paired)/sum(r['values'][usage] for r in paired)
        raw = .5*baseline + .5*recent_usage*rate
        sigma = statistics.pstdev(values)
        candidate = max(baseline-sigma, min(baseline+sigma, raw))
        reason = 'opportunity_blend'
        opportunity = {'stat': usage, 'recent_average': recent_usage, 'historical_rate': rate}
    ordered = sorted(values)
    return {'status': 'ready', 'games': len(values), 'baseline': baseline, 'candidate': candidate,
        'workload_candidate':workload_candidate(rows,stat,baseline),
        'method': reason, 'opportunity': opportunity,
        'historical_low': ordered[int((len(ordered)-1)*.1)],
        'historical_high': ordered[math.ceil((len(ordered)-1)*.9)],
        'last_five': values[-5:], 'last_result': rows[-1]['time'].isoformat()}


def forecast(history, stat, as_of):
    eligible = sorted((r for r in history if r['time'] < as_of), key=lambda r: (r['time'], r['game_id']))
    eligible = [r for r in eligible if finite(r['values'].get(stat))]
    if len({r['game_id'] for r in eligible}) != len(eligible):
        return {'stat': stat, 'status': 'duplicate_history', 'games': 0}
    result = {'stat': stat, **estimate(eligible, stat)}
    errors = []
    workload_errors=[]
    for target in eligible[-12:]:
        # Prior day only, conservative against overlapping game publication.
        past = [r for r in eligible if r['time'].date() < target['time'].date()]
        prediction = estimate(past, stat)
        if prediction['status'] == 'ready':
            actual = target['values'][stat]
            errors.append((abs(prediction['baseline']-actual), abs(prediction['candidate']-actual)))
            workload=prediction['workload_candidate']
            if workload['status']=='ready':
                workload_errors.append((abs(workload['mean']-actual),abs(prediction['baseline']-actual)))
    result['evaluation'] = {'games': len(errors),
        'baseline_mae': statistics.fmean(e[0] for e in errors) if errors else None,
        'candidate_mae': statistics.fmean(e[1] for e in errors) if errors else None,
        'type': 'retrospective_walk_forward_corrected_history'}
    result['workload_evaluation']={'games':len(workload_errors),
        'candidate_mae':statistics.fmean(e[0] for e in workload_errors) if workload_errors else None,
        'paired_baseline_mae':statistics.fmean(e[1] for e in workload_errors) if workload_errors else None}
    return result
