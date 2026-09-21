from datetime import datetime,timezone,timedelta
from src.services.signal_eligibility import blockers


def fixture():
    now=datetime.now(timezone.utc)
    row={'sport':'nfl','market':'moneyline','model_version':'v','ev_percent':10,
         'kelly_fraction':.01,'model_probability':.6,'last_seen_at':now.isoformat(),
         'game_time':(now+timedelta(hours=1)).isoformat()}
    evidence={'sport':'nfl','market':'moneyline','model_version':'v','passed_gate':True,'evaluated_at':now.isoformat()}
    return now,row,evidence


def test_no_gate_no_recommendation_even_with_positive_edge():
    now,row,evidence=fixture()
    assert blockers(row,now=now)==['missing_version_bound_validation']
    assert blockers(row,evidence,now=now)==[]
    assert 'model_validation_failed' in blockers(row,{**evidence,'passed_gate':False},now=now)
    assert 'validation_identity_mismatch' in blockers(row,{**evidence,'model_version':'other'},now=now)


def test_negative_ev_stale_or_started_never_qualify():
    now,row,evidence=fixture()
    assert 'non_positive_ev' in blockers({**row,'ev_percent':-44.65},evidence,now=now)
    assert 'stale_quote' in blockers({**row,'last_seen_at':(now-timedelta(hours=1)).isoformat()},evidence,now=now)
    assert 'event_not_pregame' in blockers({**row,'game_time':now.isoformat()},evidence,now=now)
    assert 'stale_model_validation' in blockers(row,{**evidence,'evaluated_at':(now-timedelta(days=8)).isoformat()},now=now)
