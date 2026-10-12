from src.services.retention_research import compare
from src.services.retention_research import grade_frozen


def p(pid,pos,values):
    return {'player_id':pid,'name':pid,'position':pos,'future_weeks':{
        w:({'status':'verified_bye'} if v is None else {'status':'full_scoring_projection','points':v})
        for w,v in values.items()}}


def test_future_depth_can_reverse_a_weekly_gain():
    roster=[p('qb','QB',{6:20,7:None}),p('backup','QB',{6:10,7:20}),p('def','DEF',{6:5,7:5})]
    add=p('add','DEF',{6:7,7:7})
    assert compare(roster,add,'backup',['QB','DEF'],[6])['total_gain']==2
    assert compare(roster,add,'backup',['QB','DEF'],[6,7])['reason']=='unfillable_future_lineup'


def test_no_current_week_extrapolation_or_partial_totals():
    roster=[p('a','RB',{6:10})];add=p('b','RB',{6:12})
    assert compare(roster,add,'a',['RB'],[6,7])['total_gain'] is None
    result=compare(roster,add,'a',['RB'],[6])
    assert result['total_gain']==2 and not result['serving_promoted']


def frozen():
    forecast=compare([p('a','RB',{6:10})],p('b','RB',{6:12}),'a',['RB'],[6])
    record={'forecast':forecast,'captured_at':'2026-10-01T00:00:00+00:00',
        'scoring_contract':'s','league_id':'l','player_games':{'6':{
            pid:{'game_id':'g','kickoff':'2026-10-10T00:00:00+00:00'} for pid in ('a','b')}}}
    outcomes={(6,pid):{'game_id':'g','status':'final','scoring_contract':'s','league_id':'l',
        'observed_at':'2026-10-11T00:00:00+00:00','points':points} for pid,points in [('a',15),('b',5)]}
    return record,outcomes


def test_grade_saved_choices_not_hindsight_winners():
    import json
    record,outcomes=frozen();result=grade_frozen(json.loads(json.dumps(record)),outcomes)
    assert result['actual_gain']==-10 and result['absolute_error']==12
    assert result['serving_promoted'] is False


def test_missing_and_wrong_contract_do_not_become_zero():
    record,outcomes=frozen();outcomes.pop((6,'b'))
    assert grade_frozen(record,outcomes)['actual_gain'] is None
    record,outcomes=frozen();outcomes[(6,'b')]['scoring_contract']='other'
    assert grade_frozen(record,outcomes)['actual_gain'] is None
    record,outcomes=frozen();record['captured_at']='2026-10-12T00:00:00+00:00'
    assert grade_frozen(record,outcomes)['actual_gain'] is None
