"""Independent NFL experiment. Never writes serving ratings or promotions.

Training happens offline; the API only evaluates plain JSON coefficients.
Feature history is prior-day only, so overlapping games cannot leak results.
"""
import copy
import math
from datetime import datetime

RECIPE = 'nfl_lab_logistic_v1'
FEATURES = ['elo_difference', 'last8_margin_difference', 'last8_win_rate_difference',
            'last8_scored_difference', 'last8_allowed_difference', 'rest_days_difference', 'home_venue']


def team_key(value):
    return {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'WSH': 'WAS'}.get(value, value)


def new_state(season):
    return {'elo': 1500.0, 'season': season, 'history': [], 'last_date': None, 'games': 0}


def season_state(states, team, season):
    state = states.setdefault(team, new_state(season))
    if season > state['season']:
        state['elo'] = 1500 + (state['elo'] - 1500) * (2 / 3) ** (season - state['season'])
        state['season'] = season
    return state


def summary(state, day):
    history = state['history'][-8:]
    n = len(history)
    def mean(index):
        return sum(row[index] for row in history) / n if n else 0.0
    rest = min(14, max(3, (datetime.fromisoformat(day) - datetime.fromisoformat(state['last_date'])).days)) if state['last_date'] else 7
    return {'elo': state['elo'], 'games': state['games'], 'sample': n,
            'scored': mean(0), 'allowed': mean(1), 'margin': mean(0)-mean(1),
            'win_rate': mean(2), 'rest': rest, 'last_game': state['last_date']}


def features(states, game):
    home = summary(season_state(states, game['home'], game['season']), game['date'])
    away = summary(season_state(states, game['away'], game['season']), game['date'])
    venue = 0.0 if game.get('neutral') else 1.0
    x = [home['elo']-away['elo'], home['margin']-away['margin'],
         home['win_rate']-away['win_rate'], home['scored']-away['scored'],
         home['allowed']-away['allowed'], home['rest']-away['rest'], venue]
    baseline = 1 / (1 + 10 ** (-(x[0] + 65 * venue) / 400))
    return x, baseline, home, away


def apply_game(states, game):
    home = season_state(states, game['home'], game['season'])
    away = season_state(states, game['away'], game['season'])
    hs, aws = game['home_score'], game['away_score']
    result = 1.0 if hs > aws else 0.0 if hs < aws else 0.5
    expected = features(states, game)[1]
    home['elo'] += 20 * (result-expected)
    away['elo'] -= 20 * (result-expected)
    for state, scored, allowed, win in ((home, hs, aws, result), (away, aws, hs, 1-result)):
        state['history'] = (state['history'] + [[scored, allowed, win]])[-8:]
        state['last_date'] = game['date']
        state['games'] += 1


def replay(games):
    states, rows = {}, []
    from itertools import groupby
    ordered = sorted(games, key=lambda g: (g['date'], g['id']))
    for _, daily in groupby(ordered, key=lambda g: g['date']):
        batch = list(daily)
        for game in batch:
            x, baseline, home, away = features(states, game)
            if min(home['sample'], away['sample']) >= 4 and game['home_score'] != game['away_score']:
                rows.append({'season': game['season'], 'x': x, 'baseline': baseline,
                             'y': int(game['home_score'] > game['away_score']), 'id': game['id']})
        for game in batch:
            apply_game(states, game)
    return rows, states


def probability(model, x):
    z = model['intercept'] + sum(c * (v-m)/s for c, v, m, s in
        zip(model['coef'], x, model['mean'], model['scale'], strict=True))
    return 1 / (1 + math.exp(-max(-35, min(35, z))))


def metrics(y, p):
    n = len(y)
    if not n:
        return None
    return {'n': n, 'accuracy': sum((v >= .5) == bool(t) for t,v in zip(y,p))/n,
            'brier': sum((v-t)**2 for t,v in zip(y,p))/n,
            'log_loss': -sum(t*math.log(max(1e-12,v))+(1-t)*math.log(max(1e-12,1-v)) for t,v in zip(y,p))/n}


def predict_games(artifact, scheduled, new_results):
    states = copy.deepcopy(artifact['states'])
    for game in sorted(new_results, key=lambda g: (g['date'],g['id'])):
        apply_game(states, game)
    output = []
    # Separate copies keep future season regressions from contaminating earlier fixtures.
    for game in scheduled:
        if not game.get('date') or game['home'] not in states or game['away'] not in states:
            output.append({**game, 'status': 'missing_history_or_kickoff', 'home_probability': None})
            continue
        x, base, home, away = features(copy.deepcopy(states), game)
        p = probability(artifact['model'], x)
        output.append({**game, 'status': 'experimental', 'home_probability': p,
            'away_probability': 1-p, 'baseline_home_probability': base,
            'home_features': home, 'away_features': away})
    return output
