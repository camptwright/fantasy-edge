from datetime import datetime, timedelta, timezone
from src.services.college_prospective import records

NOW=datetime(2026,9,14,tzinfo=timezone.utc)
def report():
    return {'status':'experimental','generated_at':NOW.isoformat(),'membership_fetched_at':NOW.isoformat(),
        'membership_source':'test','players':[{'player_id':'p','game_id':'g','game_time':(NOW+timedelta(days=1)).isoformat(),
         'name':'Player','position':'QB','stats':[{'stat':'passing_yards','status':'ready','baseline':200.,'candidate':210.,
          'historical_low':100.,'historical_high':300.}]}]}

def test_college_capture_exact_keys_and_policy():
    rows=records(report(),NOW)
    assert len(rows)==1
    assert rows[0]['sport']=='ncaaf'
    assert rows[0]['injury_label']=='unverified'
    assert rows[0]['id']==records(report(),NOW+timedelta(minutes=1))[0]['id']

def test_stale_future_or_started_inputs_rejected():
    assert not records(report(),NOW+timedelta(minutes=6))
    assert not records(report(),NOW-timedelta(minutes=1))
    r=report();r['membership_fetched_at']=(NOW-timedelta(hours=7)).isoformat()
    assert not records(r,NOW)
    r=report();r['players'][0]['game_time']=NOW.isoformat()
    assert not records(r,NOW)

def test_no_history_is_not_a_prediction():
    r=report();r['players'][0]['stats'][0]['status']='insufficient_history'
    assert not records(r,NOW)
