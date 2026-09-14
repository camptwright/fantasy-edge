import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from src.services.roster_stat_prospective import candidates, grade_one, publish

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
def lab():
    return {'status':'experimental', 'roster_synced_at': NOW.isoformat(), 'players':[
        {'player_id':'p', 'game_id':'g', 'game_time':(NOW+timedelta(hours=24)).isoformat(),
         'name':'Player', 'position':'QB', 'injury_status':'unknown', 'stats':[
             {'stat':'passing_yards','status':'ready','baseline':200.,'candidate':210.,
              'historical_low':100.,'historical_high':300.}]}]}

def test_capture_window_and_stale_roster():
    data = lab()
    assert len(candidates(data,NOW,'v')) == 1
    assert not candidates(data,NOW+timedelta(hours=7),'v')
    for delta in (timedelta(minutes=5),timedelta(days=4),timedelta(minutes=-1)):
        data['players'][0]['game_time']=(NOW+delta).isoformat()
        assert not candidates(data,NOW,'v')

def test_dedup_version_and_immutable_publish(tmp_path):
    first = candidates(lab(),NOW,'v')[0]
    assert candidates(lab(),NOW+timedelta(minutes=1),'v')[0]['id'] == first['id']
    assert candidates(lab(),NOW,'v2')[0]['id'] != first['id']
    path=tmp_path/'forecast.json'
    assert publish(path,first)
    assert not publish(path,{'overwritten':True})
    assert json.loads(path.read_text()) == first

def test_grades_recompute_without_mutating_forecast():
    record=candidates(lab(),NOW,'v')[0]
    game=SimpleNamespace(status='final',game_time=NOW+timedelta(hours=24))
    assert grade_one(record,game,205)['candidate_error'] == 5
    assert grade_one(record,game,215)['candidate_error'] == 5
    assert record['prediction']['candidate'] == 210
    assert grade_one(record,game,None)['status'] == 'missing_result'
    assert grade_one(record,game,0)['status'] == 'graded'
    assert grade_one(record,game,200,True)['status'] == 'pending_correction'
    game.game_time=NOW
    assert grade_one(record,game,200)['status'] == 'invalid_capture_time'

def test_pending_game_and_nonfinite():
    record=candidates(lab(),NOW,'v')[0]
    game=SimpleNamespace(status='scheduled',game_time=NOW+timedelta(hours=24))
    assert grade_one(record,game,20)['status']=='awaiting_final'
    game.status='final'
    assert grade_one(record,game,float('nan'))['status']=='missing_result'
