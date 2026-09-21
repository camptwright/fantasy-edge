from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from src.services.fantasy_decision_models import optimize, waiver_moves, historical_candidate, ros_value, trade_comparison

def player(pid,pos,points):
    return {'player_id':pid,'name':pid,'position':pos,'weekly_points':points}

def test_overlapping_flex_assignment_is_optimal():
    result=optimize([player('r','RB',20),player('w','WR',18),player('t','TE',19)],['FLEX','WRRB_FLEX'])
    assert result['total']==39
    assert {p['player_id'] for p in result['lineup']}=={'r','t'}

def test_superflex_and_duplicate_identity():
    result=optimize([player('q','QB',25),player('q','QB',25),player('r','RB',20)],['QB','SUPER_FLEX','BN'])
    assert result['total']==45

def test_missing_not_zero_and_negative_not_missing():
    assert optimize([player('r','RB',None)],['RB'])['total'] is None
    assert optimize([player('r','RB',-2)],['RB'])['total']==-2
    assert optimize([],[])['total'] is None

def test_waiver_gain_is_lineup_gain_not_player_difference():
    mine=[player('starter','WR',20),player('bench','WR',10)]
    r=waiver_moves(mine,[player('upgrade','WR',22)],['WR','BN'],{'starter'})
    assert r['moves'][0]['lineup_gain']==2
    assert r['moves'][0]['drop_id']=='bench'
    assert waiver_moves(mine,[player('depth','WR',19)],['WR','BN'],{'starter'})['moves']==[]

def test_locked_and_missing_drops_excluded():
    mine=[player('starter','WR',20),{**player('bench','WR',10),'locked':True}]
    assert waiver_moves(mine,[player('upgrade','WR',22)],['WR','BN'],{'starter'})['moves']==[]

def history():
    return [{'game_id':str(i),'time':datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=i),
             'values':{'rushing_yards':100,'rushing_attempts':20}} for i in range(10)]

def test_missing_scoring_categories_reported_not_zeroed():
    h=historical_candidate(history(),{'rush_yd':.1,'fum_lost':-2,'rush_2pt':2,'def_td':6})
    assert h['status']=='partial_scoring'
    assert h['per_game'] is None and h['modeled_subtotal']==10
    assert h['missing_scoring_keys']==['fum_lost','rush_2pt']

def test_supported_score_and_minimum_history():
    assert historical_candidate(history(),{'rush_yd':.1})['per_game']==10
    assert historical_candidate(history()[:7],{'rush_yd':.1})['modeled_subtotal'] is None

def test_ros_keeps_unknown_kickoff_and_excludes_past_and_postseason():
    now=datetime.now(timezone.utc)
    games=[SimpleNamespace(week=w,status=s,game_time=t) for w,s,t in
           [(2,'scheduled',None),(3,'scheduled',now+timedelta(days=10)),(1,'final',now-timedelta(days=1)),(19,'scheduled',None)]]
    value=ros_value({'modeled_subtotal':10},games,now)
    assert value['known_remaining_games']==2 and value['unknown_kickoffs']==1
    assert value['known_schedule_subtotal']==20 and value['full_ros_value'] is None

def test_missing_schedule_not_zero_ros():
    assert ros_value({'modeled_subtotal':10},[],datetime.now(timezone.utc))['known_schedule_subtotal'] is None

def test_trade_rejects_duplicates_and_never_invents_fairness():
    assert trade_comparison({},['a'],['a'])['status']=='invalid_package'
    result=trade_comparison({},['a'],['b'])
    assert result['verdict'] is None and result['side_a']['known_schedule_subtotal'] is None
