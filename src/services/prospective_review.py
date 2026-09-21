"""Fixed-window, paired prospective diagnostics. Never deploys a model."""
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from src.services.model_review import review

POLICY = 'first-capture-utc-day-30d-plus-7d-grading-v1'


def protocol(sport):
    return {'policy_id': 'verified-first-capture-season-aware-v2',
            'sport': sport, 'collection_days': 120 if sport in ('nfl', 'ncaaf') else 30,
            'grading_days': 7, 'minimum_independent_games': 200}


def valid(p):
    return isinstance(p, (float, int)) and math.isfinite(p) and 0 <= p <= 1


def metrics(rows, key):
    pairs = [(r[key], r['outcome']) for r in rows if valid(r.get(key)) and r.get('outcome') in (0, 1)]
    if not pairs:
        return {'samples': 0, 'brier': None, 'log_loss': None}
    return {'samples': len(pairs), 'brier': sum((p-y)**2 for p, y in pairs)/len(pairs),
        'log_loss': sum(-math.log(max(1e-15, p if y else 1-p)) for p, y in pairs)/len(pairs)}


def scorecard(records, now=None, *, policy=None, comparison='retained_baseline'):
    now = now or datetime.now(timezone.utc)
    excluded = 0
    if policy is not None:
        excluded = sum(r.get('protocol_verified') is not True for r in records)
        records = [r for r in records if r.get('protocol_verified') is True]
    if not records:
        return {'policy_id': (policy or {}).get('policy_id', POLICY),
            'protocol': policy, 'status': 'awaiting_verified_forecasts',
            'unverified_records_excluded': excluded, 'window_records': 0,
            'window_start': None, 'window_end': None, 'decision_not_before': None,
            'paired_candidate': metrics([], 'probability'), 'paired_baseline': metrics([], 'baseline'),
            'market_benchmark': metrics([], 'market_probability'), 'reliability_bins': [],
            'review': {'promotion_eligible': False, 'independent_games': 0,
                       'blockers': ['no_verified_prospective_forecasts']}, 'automatic_deployment': False}
    start = min(r['captured_at'] for r in records).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start+timedelta(days=policy['collection_days'] if policy else 30)
    decision_at = end+timedelta(days=policy['grading_days'] if policy else 7)
    window = [r for r in records if start <= r['captured_at'] < end]
    graded = [r for r in window if r['outcome'] in (0, 1) and valid(r['probability'])]
    reference = 'market_probability' if comparison == 'market_baseline' else 'baseline'
    paired = [r for r in graded if valid(r.get(reference))]
    market_paired = [r for r in graded if valid(r.get('market_probability'))]
    bins = []
    for i in range(10):
        rows = [r for r in graded if min(9, int(r['probability']*10)) == i]
        bins.append({'lower': i/10, 'upper': (i+1)/10, 'samples': len(rows),
            'mean_probability': sum(r['probability'] for r in rows)/len(rows) if rows else None,
            'observed_frequency': sum(r['outcome'] for r in rows)/len(rows) if rows else None})
    def observations(rows, field):
        return [SimpleNamespace(game_id=r['game_id'], market=r['market_key'],
            probability=r[field], outcome=r['outcome']) for r in rows]
    comparable_market = observations(paired, 'market_probability') if all(valid(r.get('market_probability')) for r in paired) else None
    result = review(observations(paired, 'probability'), observations(paired, reference),
        prospective_validated=now >= decision_at and all(r.get('protocol_verified') for r in window),
        market_benchmark=comparable_market)
    if now < decision_at:
        result['blockers'].append('fixed_evaluation_window_not_closed')
    if len(paired) != len(graded):
        result['blockers'].append('paired_baseline_incomplete')
    if any(r['status'] not in ('graded', 'push') for r in window):
        result['blockers'].append('unresolved_window_outcomes')
    result['promotion_eligible'] = not result['blockers']
    return {'policy_id': policy['policy_id'] if policy else POLICY,
        'protocol': policy, 'comparison_reference': comparison, 'unverified_records_excluded': excluded,
        'window_start': start.isoformat(), 'window_end': end.isoformat(),
        'decision_not_before': decision_at.isoformat(), 'window_records': len(window),
        'paired_candidate': metrics(paired, 'probability'), 'paired_baseline': metrics(paired, reference),
        'retained_baseline': metrics([r for r in graded if valid(r.get('baseline'))], 'baseline'),
        'market_paired_candidate': metrics(market_paired, 'probability'),
        'market_benchmark': metrics(market_paired, 'market_probability'), 'reliability_bins': bins,
        'review': result, 'automatic_deployment': False,
        'note': 'Fixed prospective window; pushes excluded; game-cluster uncertainty. No ROI or automatic approval.'}
