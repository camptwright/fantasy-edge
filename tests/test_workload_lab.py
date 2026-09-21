from datetime import datetime,timedelta,timezone
from src.services.roster_stat_model import estimate,forecast
from src.services.roster_stat_prospective import grade_one
from types import SimpleNamespace

def rows():
    now=datetime(2026,9,14,tzinfo=timezone.utc)
    return [{'game_id':str(i),'time':now-timedelta(days=30-i),'values':{'passing_yards':100.+10*i,'passing_attempts':10.+i}} for i in range(20)]

def test_workload_shrunk_between_recent_and_history():
    c=estimate(rows(),'passing_yards')['workload_candidate']
    assert c['status']=='ready'
    assert c['historical_usage']<c['expected_usage']<c['recent_usage']
    assert c['paired_games']==20

def test_missing_usage_not_proxy():
    data=rows()
    for row in data: row['values'].pop('passing_attempts')
    assert estimate(data,'passing_yards')['workload_candidate']['status']=='missing_opportunity_history'

def test_prospective_workload_grading_and_legacy():
    now=datetime(2026,9,14,tzinfo=timezone.utc)
    prediction=estimate(rows(),'passing_yards')
    record={'id':'1','version':'v','stat':'passing_yards','captured_at':now.isoformat(),'prediction':prediction}
    game=SimpleNamespace(status='final',game_time=now+timedelta(days=1))
    assert grade_one(record,game,200)['workload_error']==abs(prediction['workload_candidate']['mean']-200)
    del prediction['workload_candidate']
    assert grade_one(record,game,200)['workload_error'] is None

def test_walkforward_pairs_only():
    result=forecast(rows(),'passing_yards',datetime(2026,9,14,tzinfo=timezone.utc))
    assert result['workload_evaluation']['games']==12
