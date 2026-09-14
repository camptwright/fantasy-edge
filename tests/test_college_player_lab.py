from datetime import datetime, timedelta, timezone
import pytest
from src.services.college_player_lab import replay, membership

def history():
    start=datetime(2025,9,1,tzinfo=timezone.utc)
    rows=[{'game_id':str(i),'time':start+timedelta(days=i*7),'season':2025,'week':i,'values':{'passing_yards':100.,'passing_attempts':20.}} for i in range(8)]
    return rows+[{'game_id':'target','time':datetime(2026,9,1,tzinfo=timezone.utc),'season':2026,'week':1,'values':{'passing_yards':200.}}]

def test_prior_season_training_current_season_only():
    result=replay(history(),['passing_yards'],2026)
    assert len(result)==1
    assert result[0]['baseline_error']==100
    assert result[0]['training_games']==8

def test_future_and_same_day_dont_train():
    rows=history()
    rows.append({**rows[-1],'game_id':'later','time':rows[-1]['time']+timedelta(hours=1)})
    assert all(r['training_games']==8 for r in replay(rows,['passing_yards'],2026))

def test_missing_stats_and_small_samples():
    assert replay(history(),['receptions'],2026)==[]
    assert replay(history()[1:],['passing_yards'],2026)[0]['status']=='insufficient_history'

def test_duplicate_rejected_and_membership_fail_closed():
    with pytest.raises(ValueError): replay(history()+[history()[0]],['passing_yards'],2026)
    with pytest.raises(ValueError): membership({'children':[]})
