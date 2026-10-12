from datetime import datetime,timedelta,timezone
from src.services.prospective_review import scorecard,nfl_lab_protocol

START=datetime(2026,9,25,tzinfo=timezone.utc)

def records(n):
    return [{'game_id':str(i),'market_key':'moneyline_home','captured_at':START+timedelta(seconds=i),
        'kickoff':(START+timedelta(days=1)).isoformat(),'protocol_verified':True,
        'probability':.8,'baseline':.5,'market_probability':.6,'outcome':1,'status':'graded'} for i in range(n)]

def test_september_progress_has_no_invented_january_deadline():
    card=scorecard(records(11),START+timedelta(days=2),policy=nfl_lab_protocol())
    assert card['decision_not_before'] is None
    assert card['collection_progress']['remaining_captures']==189
    assert card['review']['promotion_eligible'] is False

def test_complete_fixed_sample_does_not_wait_120_days():
    rows=records(200)
    early=scorecard(rows,START+timedelta(days=7),policy=nfl_lab_protocol())
    assert early['review']['promotion_eligible'] is False
    ready=scorecard(rows,START+timedelta(days=9),policy=nfl_lab_protocol())
    assert ready['review']['promotion_eligible'] is True
    assert ready['decision_not_before']==(START+timedelta(days=8)).isoformat()

def test_missing_results_cannot_be_replaced_by_later_wins():
    rows=records(201);rows[0]={**rows[0],'outcome':None,'status':'awaiting_final'}
    card=scorecard(rows,START+timedelta(days=9),policy=nfl_lab_protocol())
    assert card['review']['independent_games']==199
    assert 'unresolved_window_outcomes' in card['review']['blockers']
    assert card['collection_progress']['later_captures_not_selected']==1

def test_duplicate_games_do_not_complete_sample_and_pushes_are_explicit():
    rows=records(199);rows.append(dict(rows[0]))
    card=scorecard(rows,START+timedelta(days=9),policy=nfl_lab_protocol())
    assert card['collection_progress']['remaining_captures']==1
    rows=records(201);rows[0]={**rows[0],'status':'push','outcome':None}
    card=scorecard(rows,START+timedelta(days=9),policy=nfl_lab_protocol())
    assert card['collection_progress']['pushes_excluded']==1
    assert card['review']['independent_games']==200
