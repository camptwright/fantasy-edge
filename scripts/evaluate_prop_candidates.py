"""Read-only candidate diagnostics from immutable pregame captures.

Reconstructed ablations are retrospective research, never promoted forecasts.
Run after copying this script into the serving container; no image rebuild needed.
"""
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import hashlib
import math
from pathlib import Path
import random
import uuid

from sqlalchemy import select, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat
from src.models.governance import ResultCorrection
from src.services.forecast_grading import outcome, timestamp
from src.services.stat_identity import canonical_results, canonical_stat
from src.services.shadow_props import COUNT_STATS, count_distribution, probabilities, predict, recipe_digest


def valid(p):
    return isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 1


def ablations(record):
    feature = record.get('feature_snapshot')
    sigma = record.get('inputs', {}).get('stddev')
    if not feature or not isinstance(sigma, (int, float)) or not math.isfinite(sigma) or sigma <= 0:
        return {}
    line = float(record['line'])
    baseline, recent = feature['mean'], feature['recent_mean']
    if not all(math.isfinite(v) for v in (line, baseline, recent)):
        return {}
    mean = max(baseline-sigma, min(baseline+sigma, .5*baseline+.5*recent))
    result = {'reconstructed:recency_normal_v1': .5*math.erfc((line-mean)/(sigma*math.sqrt(2)))}
    if feature.get('opportunity'):
        result['reconstructed:opportunity_normal_v1'] = predict(feature, line, sigma)['opportunity_recent_normal_v1']['model_probability']
    if feature['canonical_stat'] in COUNT_STATS:
        try:
            dist, _ = count_distribution(baseline, .5*feature['variance']+.5*max(0, baseline))
            result['reconstructed:count_only_v1'] = probabilities(dist, line)['model_probability']
        except ValueError:
            pass
    return result


def loss(p, y):
    return -math.log(max(1e-15, p if y else 1-p))


def summarize(rows):
    n = len(rows)
    if not n:
        return {'samples': 0, 'independent_games': 0, 'promotion_eligible': False}
    clusters = defaultdict(list)
    for row in rows:
        clusters[row['game_id']].append((row['candidate']-row['outcome'])**2 - (row['baseline']-row['outcome'])**2)
    aggregate = [(sum(v), len(v)) for v in clusters.values()]
    rng = random.Random(20260908)
    draws = []
    if len(aggregate) >= 2:
        for _ in range(1000):
            sample = rng.choices(aggregate, k=len(aggregate))
            draws.append(sum(x for x, _ in sample)/sum(count for _, count in sample))
        draws.sort()
    def metric(field):
        return {'brier': sum((r[field]-r['outcome'])**2 for r in rows)/n,
                'log_loss': sum(loss(r[field], r['outcome']) for r in rows)/n}
    candidate, baseline = metric('candidate'), metric('baseline')
    return {'samples': n, 'independent_games': len(clusters), 'candidate': candidate, 'retained_baseline': baseline,
        'delta_brier': candidate['brier']-baseline['brier'],
        'delta_log_loss': candidate['log_loss']-baseline['log_loss'],
        'game_cluster_delta_brier_95pct': [draws[24], draws[974]] if draws else None,
        'promotion_eligible': False,
        'note': 'Exploratory; negative deltas favor candidate. Confidence intervals are not multiple-comparison adjusted.'}


def select_records(directory):
    selected, exclusions = {}, Counter()
    for path in sorted(directory.glob('*.json')):
        payload = json.loads(path.read_text())  # corrupt archive fails closed
        if payload.get('schema_version') != 1:
            raise ValueError('unsupported capture schema')
        captured = timestamp(payload['captured_at'])
        for record in payload['records']:
            if record['kind'] != 'player':
                continue
            baseline = record['prediction'].get('baseline_model_probability')
            if not valid(baseline):
                exclusions['missing_retained_baseline_capture_rows'] += 1
                continue
            candidates = {f"captured:{name}:{value.get('recipe_version', 'legacy')}": value.get('model_probability')
                          for name, value in record.get('shadow_predictions', {}).items()}
            feature = record.get('feature_snapshot')
            if feature:
                try:
                    as_of = timestamp(feature['as_of'])
                    last_result = timestamp(feature['last_result_at'])
                    if as_of > captured or last_result >= as_of or feature['canonical_stat'] != canonical_stat(record['market']):
                        exclusions['invalid_feature_timing_capture_rows'] += 1
                        continue
                    candidates.update(ablations(record))
                except (KeyError, ValueError, TypeError):
                    exclusions['invalid_feature_capture_rows'] += 1
                    continue
            for recipe, p in candidates.items():
                if not valid(p):
                    continue
                key = (record['game_id'], record['player_id'], canonical_stat(record['market']), recipe)
                rank = (captured, record['quote_id'])
                if key not in selected or rank < selected[key][0]:
                    selected[key] = (rank, record, p, baseline)
    return selected, exclusions


async def evaluate():
    root = Path(get_settings().raw_archive_dir)
    selected, exclusions = select_records(root/'forecasts')
    game_ids = sorted({key[0] for key in selected})
    games, stats, disputed = {}, {}, set()
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        for start in range(0, len(game_ids), 500):
            batch = [uuid.UUID(g) for g in game_ids[start:start+500]]
            games.update({str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_(batch)))).all()})
            facts = (await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(batch)))).all()
            stats.update({(str(p), str(g), s): v for (p, g, s), v in canonical_results(facts).items()})
            pending = (await db.scalars(select(PlayerGameStat).join(ResultCorrection, ResultCorrection.stat_id == PlayerGameStat.id)
                .where(PlayerGameStat.game_id.in_(batch), ResultCorrection.status == 'pending'))).all()
            disputed.update((str(f.player_id), str(f.game_id), canonical_stat(f.stat_type)) for f in pending)
    groups, totals, counts = defaultdict(list), defaultdict(list), Counter()
    unique = defaultdict(set)
    capture_times = []
    for key, ((captured, _), record, probability, baseline) in selected.items():
        game = games.get(key[0])
        status, y = outcome(record, game, stats, captured, disputed)
        counts[status] += 1
        unique[(game.sport if game else 'unknown', status)].add(key[:3])
        if status != 'graded':
            continue
        capture_times.append(captured)
        row = {'game_id': key[0], 'candidate': probability, 'baseline': baseline, 'outcome': y}
        groups[(game.sport, key[2], key[3])].append(row)
        totals[(game.sport, key[3])].append(row)
    return {'evaluated_at': datetime.now(timezone.utc).isoformat(), 'status': 'research_only',
        'recipe_digest': recipe_digest(), 'selection': 'Earliest valid capture per player/game/canonical-stat/recipe across app versions.',
        'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'retained_baseline': 'Saved baseline_model_probability; never substitute current or served override probabilities.',
        'counts_by_candidate_outcome': dict(counts), 'capture_row_exclusions': dict(exclusions),
        'unique_outcomes_by_sport': [{'sport': sport, 'status': state, 'outcomes': len(keys)}
            for (sport, state), keys in sorted(unique.items())],
        'first_graded_capture': min(capture_times).isoformat() if capture_times else None,
        'last_graded_capture': max(capture_times).isoformat() if capture_times else None,
        'families': [{'sport': s, 'market': m, 'recipe': r, **summarize(rows)} for (s,m,r), rows in sorted(groups.items())],
        'sport_summaries': [{'sport': s, 'recipe': r, **summarize(rows)} for (s,r), rows in sorted(totals.items())],
        'limitations': ['Captured recipes are prospective predictions; reconstructed ablations were not frozen before outcomes.',
            'Opportunity variants require archived opportunity features; comparisons use only paired samples.',
            'Pushes, missing results, pending corrections, and invalid timing are excluded, never filled with zero.',
            'Historical result publication times are unavailable. No injury or future-role assumptions are added.',
            'Across-recipe summaries can have different cohorts; pooled markets are descriptive, not deployment criteria.',
            'Small game counts, fixed-window requirements, and multiple testing prevent promotion conclusions.'],
        'promotion_eligible': False, 'serving_parameters_changed': False}


if __name__ == '__main__':
    from src.scheduler.calibration import archive
    result = asyncio.run(evaluate())
    path = archive('candidate-evaluation', result)
    print(json.dumps({'archive': path, 'counts': result['counts_by_candidate_outcome'],
                      'summaries': result['sport_summaries']}, indent=2))
