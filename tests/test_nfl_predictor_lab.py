import copy
import json
from pathlib import Path

import pytest

from src.services.nfl_predictor_lab import (
    apply_game, features, metrics, new_state, predict_games, probability, replay, season_state, team_key,
)


def fixture(i, hs=24, aws=17, date=None):
    return {'id':str(i),'season':2025,'date':date or f'2025-09-{i+1:02d}',
            'home':'SEA','away':'NE','home_score':hs,'away_score':aws,'neutral':False}


def test_current_and_future_scores_cannot_change_pregame_features():
    games = [fixture(i) for i in range(10)]
    before,_ = replay(games)
    changed = copy.deepcopy(games)
    changed[6]['home_score'] = 0
    changed[9]['home_score'] = 80
    after,_ = replay(changed)
    assert [r['x'] for r in before if int(r['id']) <= 6] == [r['x'] for r in after if int(r['id']) <= 6]
    assert next(r['y'] for r in before if r['id']=='6') != next(r['y'] for r in after if r['id']=='6')


def test_same_day_results_not_used_by_other_pregame_features():
    games = [fixture(i) for i in range(6)]
    games.extend([fixture(7,date='2025-09-08'),fixture(8,date='2025-09-08')])
    rows,_ = replay(games)
    assert rows[-1]['x'] == rows[-2]['x']


def test_neutral_removes_elo_home_advantage():
    g = fixture(0)
    assert features({},g)[1] > .5
    g['neutral'] = True
    assert features({},g)[1] == .5


def test_season_regression_only_once():
    states = {'SEA':new_state(2025)}
    states['SEA']['elo'] = 1650
    assert season_state(states,'SEA',2026)['elo'] == 1600
    assert season_state(states,'SEA',2026)['elo'] == 1600


def test_ties_update_history_but_not_binary_training():
    games=[fixture(i,21,21) for i in range(6)]
    rows,states=replay(games)
    assert not rows
    assert states['SEA']['history'][-1][2] == .5


def test_history_window_and_rest_cap():
    states={}
    for i in range(10):
        apply_game(states,fixture(i))
    assert len(states['SEA']['history']) == 8
    _,_,home,_=features(states,fixture(11,date='2026-09-01'))
    assert home['rest']==14


def test_metrics_and_probability_finite():
    model={'coef':[1.0],'mean':[0.0],'scale':[1.0],'intercept':0.0}
    assert probability(model,[0]) == .5
    assert 0 < probability(model,[1e10]) < 1
    assert metrics([0,1],[0,1])['accuracy']==1
    assert metrics([0,1],[0,1])['brier']==0
    assert metrics([],[]) is None


def test_saved_artifact_is_reproducible_and_predictions_do_not_mutate_it():
    artifact=json.loads((Path(__file__).resolve().parents[1]/'config/nfl_predictor_lab.json').read_text())
    before=copy.deepcopy(artifact)
    game={**fixture(0,date='2026-09-09'),'season':2026}
    result=predict_games(artifact,[game],[])[0]
    assert 0 < result['home_probability'] < 1
    assert result['home_probability']+result['away_probability']==pytest.approx(1)
    assert artifact==before
    assert [s['season'] for s in artifact['evaluation']['seasons']] == [2022,2023,2024,2025]
    assert sum(s['candidate']['n'] for s in artifact['evaluation']['seasons']) == artifact['evaluation']['candidate']['n']


def test_missing_history_or_kickoff_withheld():
    artifact={'states':{},'model':{}}
    result=predict_games(artifact,[fixture(0)],[])[0]
    assert result['home_probability'] is None


def test_franchise_aliases():
    assert team_key('OAK')==team_key('LV')
    assert team_key('LAR')==team_key('STL')==team_key('LA')
