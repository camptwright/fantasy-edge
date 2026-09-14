"""Fixed historical-control vs recency candidate; never imported by serving."""
from collections import defaultdict
import hashlib
import json
import statistics

RECIPE = {'id': 'period_empirical_recency_v1', 'minimum_history': 8,
          'control_window': 20, 'candidate_window': 8, 'train_season': 2024,
          'test_season': 2025, 'binary_beta_prior': [1, 1]}


def evaluate(games):
    history, scores, predictions = defaultdict(list), defaultdict(list), []
    # Update histories only after every game on that date is predicted.
    days = defaultdict(list)
    for game in games:
        days[game['date']].append(game)
    for day in sorted(days):
        additions = []
        for game in days[day]:
            for row in game['labels']:
                key = (row['player_id'], row['market'])
                past = history[key]
                additions.append((key, row['value']))
                if game['season'] != RECIPE['test_season'] or len(past) < RECIPE['minimum_history']:
                    continue
                binary = row['market'] in ('first_td_scorer', 'last_td_scorer')
                def predict(window):
                    values = past[-window:]
                    return ((sum(values)+1)/(len(values)+2) if binary else statistics.fmean(values))
                control, candidate = predict(20), predict(8)
                y = row['value']
                scores[row['market']].append((game['game_id'], (control-y)**2, (candidate-y)**2))
                predictions.append({'game_id': game['game_id'], 'player_id': row['player_id'],
                    'market': row['market'], 'actual': y, 'control': control, 'candidate': candidate})
        for key, value in additions:
            history[key].append(value)
    metrics = []
    for market, rows in sorted(scores.items()):
        by_game = defaultdict(list)
        for gid, control, candidate in rows:
            by_game[gid].append(candidate-control)
        deltas = [statistics.fmean(v) for v in by_game.values()]
        metrics.append({'market': market, 'rows': len(rows), 'games': len(by_game),
            'metric': 'brier' if 'td_scorer' in market else 'mse',
            'control': statistics.fmean(r[1] for r in rows),
            'candidate': statistics.fmean(r[2] for r in rows),
            'game_weighted_delta': statistics.fmean(deltas),
            'game_delta_standard_error': statistics.stdev(deltas)/len(deltas)**.5 if len(deltas)>1 else None})
    return {'recipe': RECIPE, 'recipe_hash': hashlib.sha256(json.dumps(RECIPE, sort_keys=True).encode()).hexdigest(),
            'metrics': metrics, 'predictions': predictions, 'serving_enabled': False,
            'evaluation_type': 'retrospective_conditional_on_recorded_participation',
            'baseline_note': 'Research history control, not the retained production full-game model.',
            'limitations': ['No historical period sportsbook lines: no EV/ROI claims.',
                'Corrected historical data has no point-in-time publication snapshots.',
                'Scorer probabilities are marginal research estimates, not a normalized game market.',
                'Independent final-boxscore and pregame participation validation still required.']}
