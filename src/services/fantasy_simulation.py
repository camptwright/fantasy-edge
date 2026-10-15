"""Deterministic empirical research, not a calibrated win probability."""
import hashlib
import numpy as np
from src.services.roster_stat_model import finite
from src.services.availability_status import normalize_status


def assumed_scale(p):
    evidence=p.get('distribution_evidence',{})
    if evidence.get('status')!='assumed_position_prior':return None
    if evidence.get('recipe')!='explicit_specialist_default_v1':return None
    expected={'K':5.0,'DEF':7.0}.get(p.get('position'))
    return expected if expected is not None and evidence.get('standard_deviation')==expected else None


def eligibility_reasons(p):
    reasons=[]
    if p.get('game_availability',{}).get('hold_recommendation'):
        reasons.append('event_availability_hold')
    if p.get('locked',True): reasons.append('started_or_unbound_game')
    if p.get('weekly_evidence',{}).get('status')!='pregame_provider_projection': reasons.append('missing_fresh_projection')
    if not finite(p.get('weekly_points')): reasons.append('invalid_projection')
    if normalize_status(p.get('injury_status')) not in (None, 'ACTIVE'):
        reasons.append('availability_review_required')
    samples=p.get('score_samples',[])
    if (len(samples)<8 or not all(finite(x) for x in samples)) and assumed_scale(p) is None:
        reasons.append('incomplete_scoring_distribution')
    return reasons


def legal_lineups(pool,slots,limit=512):
    from src.services.fantasy_decision_models import FLEX
    results={}; truncated=False; visited=0
    def visit(picks):
        nonlocal truncated,visited
        visited+=1
        if visited>50000:
            truncated=True;return
        if len(picks)==len(slots):
            key=tuple(sorted(picks))
            if key not in results:
                if len(results)>=limit:
                    truncated=True;return
                results[key]=tuple(picks)
            return
        for p in sorted(pool,key=lambda p:(-p['weekly_points'],p['player_id'])):
            if truncated:return
            previous=[i for i in range(len(picks)) if slots[i]==slots[len(picks)]]
            if previous and p['player_id']<=picks[previous[-1]]:continue
            if p['player_id'] not in picks and p.get('position') in FLEX.get(slots[len(picks)],{slots[len(picks)]}):
                visit(picks+[p['player_id']])
    visit([])
    return list(results.values()),truncated


def evaluate(players, starters, opponent, slots, *, draws=4000):
    from src.services.fantasy_decision_models import optimize, FLEX, RESERVE
    if not isinstance(draws,int) or isinstance(draws,bool) or draws<100:
        raise ValueError('At least 100 simulation draws are required')
    by_id = {p['player_id']: p for p in players}
    slots = [s for s in slots if s not in RESERVE]
    base = {'status': 'withheld', 'win_probability': None, 'validated': False,
            'assumptions': ['Independent player outcomes; correlations not modeled.',
                'Historical scoring variability centered on fresh projections; no injury/participation simulation.',
                'Bounded legal-lineup enumeration; search truncation is disclosed.']}
    def eligible(pid):
        p = by_id.get(pid, {})
        return not eligibility_reasons(p)
    if (len(starters) != len(slots) or len(opponent) != len(slots) or
        len(set(starters+opponent)) != len(starters+opponent) or
        not all(eligible(pid) for pid in starters+opponent)):
        return {**base, 'reason': 'Incomplete pregame lineup/distribution or availability coverage.',
                'blocked_player_ids':sorted({pid for pid in starters+opponent if not eligible(pid)}),
                'player_blockers':[{'player_id':pid,'name':by_id.get(pid,{}).get('name',pid),
                    'reasons':eligibility_reasons(by_id.get(pid,{})),
                    'platform_history_games':by_id.get(pid,{}).get('distribution_evidence',{}).get('games',0)}
                    for pid in sorted(set(starters+opponent)) if not eligible(pid)]}
    if any(by_id[pid].get('position') not in FLEX.get(slot,{slot})
           for ids in (starters,opponent) for pid,slot in zip(ids,slots)):
        return {**base, 'reason': 'Starter positions do not match the league slot order.'}
    pool = [p for p in players if p.get('is_mine') and eligible(p['player_id'])]
    candidates = [starters]
    optimum = optimize(pool, slots)
    if optimum['total'] is not None:
        candidates.append([p['player_id'] for p in optimum['lineup']])
    alternatives,truncated=legal_lineups(pool,slots)
    candidates.extend(alternatives)
    candidates = sorted(set(tuple(c) for c in candidates))
    samples = {}
    sample_ids=sorted(set(opponent) | {pid for c in candidates for pid in c})
    weekly={pid:{(r.get('season','current'),r['week']):r['points'] for r in by_id[pid].get('distribution_evidence',{}).get('evidence',[])
        if finite(r.get('points'))} for pid in sample_ids}
    common_weeks=sorted(set.intersection(*(set(weekly[pid]) for pid in sample_ids))) if sample_ids else []
    joint=len(common_weeks)>=8 and not any(assumed_scale(by_id[pid]) is not None for pid in sample_ids)
    # Select the candidate on one stream; report its estimate on an independent
    # stream. Otherwise searching hundreds of lineups selects Monte Carlo noise.
    indices=np.random.default_rng(41621).integers(len(common_weeks),size=2*draws) if joint else None
    for pid in sample_ids:
        p = by_id[pid]
        rng = np.random.default_rng(int(hashlib.sha256(pid.encode()).hexdigest()[:16], 16))
        scale=assumed_scale(p)
        if scale is not None:
            samples[pid]=rng.normal(p['weekly_points'],scale,2*draws)
            continue
        values = np.asarray([weekly[pid][w] for w in common_weeks] if joint else p['score_samples'], dtype=float)
        residuals=values-values.mean()
        samples[pid] = (residuals[indices] if joint else rng.choice(residuals, 2*draws))+p['weekly_points']
    other = sum(samples[pid] for pid in opponent)
    def score(ids, selection=False):
        segment=slice(0,draws) if selection else slice(draws,None)
        total = sum(samples[pid] for pid in ids)[segment]
        wins=total>other[segment]
        probability=float(np.mean(wins))
        return {'player_ids': list(ids), 'estimated_win_probability': probability,
                'monte_carlo_standard_error':float(np.sqrt(probability*(1-probability)/draws)),
                'estimated_tie_probability': float(np.mean(total == other[segment])),
                'expected_points': sum(by_id[pid]['weekly_points'] for pid in ids),
                'floor_p10': float(np.quantile(total, .1)), 'ceiling_p90': float(np.quantile(total, .9))}
    current = score(starters)
    selected = max((score(c,selection=True) for c in candidates), key=lambda r: (r['estimated_win_probability'], r['expected_points']))
    best = score(selected['player_ids'])
    if joint:
        base['assumptions'][0]='Shared historical league-week residual draws preserve observed co-movement, not a validated current-matchup correlation model.'
    defaults=[{'player_id':pid,'position':by_id[pid]['position'],
        'standard_deviation':assumed_scale(by_id[pid])} for pid in sample_ids if assumed_scale(by_id[pid]) is not None]
    if defaults:
        base['assumptions'].append('Explicit K/DST defaults: normal scores around provider projection, SD 5/7 fantasy points. Assumed, not fitted or calibrated; no synthetic history counted.')
    return {**base, 'status': 'estimated_research', 'reason': 'Unvalidated empirical simulation; not automated lineup advice.',
            'current': current, 'candidate': best, 'draws': draws, 'candidates_evaluated': len(candidates),
            'search_truncated':truncated,'search_limit':512,
            'selection_draws':draws,'independent_reporting_draws':draws,
            'assumed_specialist_distributions':defaults,
            'uncertainty_scope':'Monte Carlo error only; excludes model misspecification and injury uncertainty.',
            'sampling_method':'joint_platform_week_residuals' if joint else 'independent_player_residuals',
            'common_history_weeks':common_weeks if joint else [],
            'estimated_win_probability_delta': best['estimated_win_probability']-current['estimated_win_probability']}
