"""Build a separate JSON experiment, with expanding-season validation.

Run manually: python -m scripts.train_nfl_predictor_lab
No production DB, rating table, credentials, odds calls or model promotions.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy as nfl
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.services.nfl_predictor_lab import FEATURES, RECIPE, metrics, probability, replay, team_key


def fit(rows):
    scaler = StandardScaler()
    x = scaler.fit_transform([r['x'] for r in rows])
    clf = LogisticRegression(C=1.0, max_iter=1000, random_state=17).fit(x, [r['y'] for r in rows])
    return {'coef': clf.coef_[0].tolist(), 'intercept': float(clf.intercept_[0]),
            'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist()}


def main():
    source = nfl.load_schedules(True).to_dicts()
    games, venues = [], {}
    for r in source:
        season = int(r['season'])
        if season < 2015 or r['game_type'] == 'PRE':
            continue
        day = str(r['gameday'])[:10]
        g = {'id': r['game_id'], 'season': season, 'date': day,
             'home': team_key(r['home_team']), 'away': team_key(r['away_team']),
             'neutral': r.get('location') == 'Neutral'}
        venues[f"{season}:{g['home']}:{g['away']}:{day}"] = g['neutral']
        if season <= 2025 and r['home_score'] is not None and r['away_score'] is not None:
            games.append({**g, 'home_score': int(r['home_score']), 'away_score': int(r['away_score'])})
    if len({g['id'] for g in games}) != len(games):
        raise ValueError('Duplicate historical game IDs')
    rows, states = replay(games)
    reports, all_y, all_p, all_base, all_home = [], [], [], [], []
    for year in (2022, 2023, 2024, 2025):
        train = [r for r in rows if r['season'] < year]
        test = [r for r in rows if r['season'] == year]
        if len(train) < 500 or len(test) < 200:
            raise ValueError(f'Insufficient history for season {year}')
        model = fit(train)
        y = [r['y'] for r in test]
        p = [probability(model, r['x']) for r in test]
        base = [r['baseline'] for r in test]
        prior = sum(r['y'] for r in train)/len(train)
        home = [prior] * len(test)
        reports.append({'season': year, 'train_games': len(train), 'candidate': metrics(y,p),
                        'elo': metrics(y,base), 'home_prior': metrics(y,home)})
        all_y.extend(y)
        all_p.extend(p)
        all_base.extend(base)
        all_home.extend(home)
    bins = []
    for lo,hi in [(0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.01)]:
        selected = [(p,y) for p,y in zip(all_p,all_y) if lo <= p < hi]
        if selected:
            bins.append({'range': f'{int(lo*100)}–{min(100,int(hi*100))}%', 'n':len(selected),
                         'predicted':sum(p for p,y in selected)/len(selected),
                         'observed':sum(y for p,y in selected)/len(selected)})
    artifact = {'recipe': RECIPE, 'features': FEATURES, 'trained_at': datetime.now(timezone.utc).isoformat(),
        'history_games': len(games), 'training_games': len(rows), 'first_season':2015,'last_season':2025,
        'history_through':max(g['date'] for g in games),
        'source':'https://github.com/nflverse/nfldata/blob/master/data/games.csv',
        'history_hash':hashlib.sha256(json.dumps(games,sort_keys=True).encode()).hexdigest(),
        'model':fit(rows), 'states':states,'venues':venues,
        'evaluation': {'seasons':reports,'candidate':metrics(all_y,all_p), 'elo':metrics(all_y,all_base),
                       'home_prior':metrics(all_y,all_home),'reliability':bins}}
    artifact['version'] = hashlib.sha256(json.dumps({'recipe':RECIPE,'model':artifact['model'],
        'history_hash':artifact['history_hash']},sort_keys=True).encode()).hexdigest()[:16]
    path = Path(__file__).resolve().parents[1]/'config'/'nfl_predictor_lab.json'
    path.write_text(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:artifact[k] for k in ['version','history_games','training_games','evaluation']},indent=2))


if __name__ == '__main__':
    main()
