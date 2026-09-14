"""Prospective empirical probability candidate, isolated from serving and grading."""
import math
from datetime import datetime

RECIPE = 'period_empirical_dirichlet_v1_window20_min8'


def predict(history, player, market, line, captured_at):
    if 'td_scorer' in market:
        return {'status': 'requires_joint_scorer_model'}
    if not isinstance(line, (int, float)) or isinstance(line, bool) or not math.isfinite(line):
        return {'status': 'invalid_line'}
    # Only already published, complete prior-day artifacts may supply labels.
    values = []
    for game in sorted(history, key=lambda r: (r['date'], r['game_id'])):
        if game['date'] >= captured_at.date().isoformat():
            continue
        published = datetime.fromisoformat(game['available_at'])
        if published.tzinfo is None or published >= captured_at:
            continue
        for row in game['labels']:
            if row['player_id'] == player and row['market'] == market:
                value = row.get('value')
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not float(value).is_integer()):
                    return {'status': 'invalid_history_outcome'}
                values.append((game['game_id'], value))
    if len({g for g, _ in values}) != len(values):
        return {'status': 'duplicate_history_game'}
    values = values[-20:]
    if len(values) < 8:
        return {'status': 'insufficient_published_history', 'history_games': len(values)}
    # Three mutually exclusive outcomes including pushes; symmetric Jeffreys
    # smoothing is fixed before any prospective results are observed.
    push_possible = float(line).is_integer()
    n = len(values) + (1.5 if push_possible else 1)
    return {'status': 'research_prediction', 'recipe': RECIPE,
        'over': (sum(v > line for _, v in values)+.5)/n,
        'under': (sum(v < line for _, v in values)+.5)/n,
        'push': (sum(v == line for _, v in values)+.5)/n if push_possible else 0.0,
        'history_game_ids': [g for g, _ in values], 'serving_enabled': False}
