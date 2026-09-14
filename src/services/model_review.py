"""Paired evaluation checks; missing evidence blocks model promotion.

Bootstrap units are games, not individual correlated props. This review does
not itself deploy a candidate or claim to test chronological data provenance.
"""
import math
import random
from collections import defaultdict


def review(candidate, baseline, *, prospective_validated=False, market_benchmark=None):
    def keyed(rows):
        result = {}
        for row in rows:
            key = (row.game_id, row.market)
            if key in result or row.game_id is None or row.outcome not in (0, 1):
                raise ValueError('Evaluation requires unique game/market observations')
            if not math.isfinite(row.probability) or not 0 <= row.probability <= 1:
                raise ValueError('Invalid evaluation probability')
            result[key] = row
        return result
    c, b = keyed(candidate), keyed(baseline)
    if c.keys() != b.keys() or any(c[k].outcome != b[k].outcome for k in c):
        raise ValueError('Candidate and baseline must grade identical events and outcomes')
    blockers = []
    if not prospective_validated:
        blockers.append('prospective_validation_pending')
    if market_benchmark is None:
        blockers.append('market_benchmark_missing')
    grouped = defaultdict(list)
    loss_deltas = []
    def loss(row):
        p = min(max(row.probability, 1e-9), 1-1e-9)
        return -(row.outcome*math.log(p)+(1-row.outcome)*math.log1p(-p))
    for key in c:
        grouped[key[0]].append((c[key].probability-c[key].outcome)**2 -
                              (b[key].probability-b[key].outcome)**2)
        loss_deltas.append(loss(c[key])-loss(b[key]))
    differences = [sum(v)/len(v) for v in grouped.values()]
    interval = None
    if len(differences) < 200:
        blockers.append('fewer_than_200_independent_games')
    else:
        rng = random.Random(20260905)
        means = sorted(sum(rng.choices(differences, k=len(differences)))/len(differences)
                       for _ in range(1000))
        interval = [means[25], means[974]]
        if interval[1] >= 0:
            blockers.append('brier_improvement_uncertain')
    delta = sum(differences)/len(differences) if differences else None
    loss_delta = sum(loss_deltas)/len(loss_deltas) if loss_deltas else None
    if delta is None or delta >= 0 or loss_delta >= 0:
        blockers.append('both_scores_must_improve')
    if market_benchmark is not None:
        market = keyed(market_benchmark)
        if market.keys() != c.keys() or any(market[k].outcome != c[k].outcome for k in c):
            blockers.append('market_benchmark_not_comparable')
        elif not c or sum((c[k].probability-c[k].outcome)**2 for k in c) >= sum(
                (market[k].probability-market[k].outcome)**2 for k in c) or sum(
                loss(c[k]) for k in c) >= sum(loss(market[k]) for k in c):
            blockers.append('does_not_beat_market_benchmark')
    return {'independent_games': len(grouped), 'brier_delta': delta,
            'log_loss_delta': loss_delta, 'brier_delta_interval_95': interval,
            'promotion_eligible': not blockers, 'blockers': blockers,
            'note': 'Game-cluster bootstrap; temporal drift and data provenance need separate review.'}
