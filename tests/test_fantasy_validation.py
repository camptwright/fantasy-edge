from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from src.services.fantasy_schedule import validate, coverage
from src.ingest.espn import _kickoff_from_event
from src.ingest.fantasy_scoring import parse, special_teams
from src.services.fantasy_prospective import grade, candidates, grade_weekly

def test_tbd_is_not_midnight():
    assert _kickoff_from_event({'date':'2027-01-10T05:00Z','competitions':[{'timeValid':False}]}) is None

def test_schedule_incomplete_and_duplicate_rejected():
    assert not coverage([])['complete']
    with pytest.raises(ValueError): validate([],2026)
    e={'id':'1','season':{'year':2026,'type':2},'week':{'number':1},'competitions':[{'competitors':[
        {'homeAway':'home','team':{'id':'a'}},{'homeAway':'away','team':{'id':'b'}}]}]}
    with pytest.raises(ValueError,match='duplicate'): validate([e,e],2026)

def test_scoring_missing_is_not_zero_and_total_fumbles_not_double_counted():
    assert parse({})=={}
    assert parse({'fumbles_lost_total':'2','sack_fumbles_lost':'1'})=={'fumbles_lost':2}
    assert parse({'passing_2pt_conversions':'0'})=={'passing_2pt_conversions':0}
    with pytest.raises(ValueError):parse({'fumbles_lost_total':'nan'})

def test_st_requires_end_marker_and_attribution():
    flags={k:'0' for k in ('defensive_two_point_conv','defensive_extra_point_conv','safety','two_point_attempt','extra_point_attempt')}
    play={**flags,'game_id':'g','play_id':'1','kickoff_attempt':'1','fumble':'1','fumble_forced':'1',
        'forced_fumble_player_1_player_id':'a','fumbled_1_team':'X',
        'fumble_recovery_1_team':'Y','fumble_recovery_1_player_id':'b'}
    end={**flags,'game_id':'g','play_id':'2','desc':'END GAME','total_home_score':'7','total_away_score':'3'}
    values,valid=special_teams([play,end])
    assert valid['g']==(7,3) and values['g']['a']['special_teams_ff']==1 and values['g']['b']['special_teams_fum_rec']==1
    assert special_teams([play])[1]=={}
    assert special_teams([{**play,'forced_fumble_player_1_player_id':''},end])[1]=={}
    assert special_teams([play,play,end])[1]=={}

def record():
    return {'id':'r','version':'v','league_id':'l','scoring_cohort':'c',
        'captured_at':'2026-09-01T00:00:00+00:00','prediction':{'scoring_weights':{'receptions':1},
        'status':'candidate','baseline_subtotal':4,'modeled_subtotal':5}}

def test_prospective_grades_corrected_results_without_changing_forecast():
    r=record();g=SimpleNamespace(game_time=datetime(2026,9,2,tzinfo=timezone.utc),status='final')
    assert grade(r,g,{})['status']=='missing_scoring_results'
    assert grade(r,g,{'receptions':6},True)['status']=='pending_correction'
    assert grade(r,g,{'receptions':6})['candidate_error']==1
    assert grade(r,g,{'receptions':7})['candidate_error']==2
    assert r['prediction']['modeled_subtotal']==5

def test_no_backdated_or_stale_capture():
    now=datetime(2026,9,2,tzinfo=timezone.utc)
    assert candidates({'status':'candidate','coverage':{'stale_inputs':True}},now,'v')==[]
    g=SimpleNamespace(game_time=datetime(2026,8,31,tzinfo=timezone.utc),status='final')
    assert grade(record(),g,{'receptions':6})['status']=='invalid_capture_time'

def test_weekly_grading_uses_frozen_lineups_not_reoptimized_hindsight():
    r={'id':'w','lineups':{'your_starters':['a'],'opponent_starters':['b']},
       'matchup':{'projected_margin':3},'waivers':{'before':{'lineup':[{'player_id':'a'}]},
       'moves':[{'add_id':'c','after_lineup':[{'player_id':'c'}]}]}}
    result=grade_weekly(r,{'a':10,'b':12,'c':8})
    assert result['margin_error']==5
    assert result['waivers'][0]['realized_lineup_gain']==-2
    assert grade_weekly(r,{'a':10,'b':12})['waivers'][0]['status']=='missing_player_points'

def test_full_ros_requires_both_schedule_and_scoring():
    from src.services.fantasy_decision_models import ros_value,player_scoring
    now=datetime.now(timezone.utc)
    g=SimpleNamespace(week=18,status='scheduled',game_time=None)
    assert ros_value({'per_game':10,'modeled_subtotal':10},[g],now,schedule_complete=True)['full_ros_value']==10
    assert ros_value({'per_game':None,'modeled_subtotal':10},[g],now,schedule_complete=True)['full_ros_value'] is None
    league=SimpleNamespace(platform='espn',raw={},scoring_settings={'rec':1})
    assert player_scoring(league,'WR')[1]==['unverified_espn_scoring_rules']

@pytest.mark.asyncio
async def test_espn_scoring_evidence_is_retained_without_account_payload():
    from unittest.mock import AsyncMock
    from src.ingest.espn_fantasy import _upsert_league
    db=AsyncMock(); scoring={'scoringItems':[{'statId':53,'points':1}]}
    await _upsert_league(db,'espn:1','1',2026,{},['WR'],{'rec':1},
        {'settings':{'scoringSettings':scoring},'account':'not retained'})
    params=db.execute.call_args.args[0].compile().params
    assert params['raw']=={'league_id':'1','scoringSettings':scoring}

def test_espn_equal_td_groups_and_kicking_buckets_are_exact():
    from src.services.fantasy_decision_models import player_scoring
    items=[{'statId':i,'points':6} for i in (93,101,102,103,104)]
    items+=[{'statId':80,'points':3},{'statId':53,'points':1,'pointsOverrides':{'4':1.5}}]
    league=SimpleNamespace(platform='espn',raw={'scoringSettings':{'scoringItems':items}},scoring_settings={})
    weights,gaps=player_scoring(league,'TE')
    assert gaps==[] and weights['st_td']==6 and weights['idp_def_tds']==6 and weights['rec']==1.5
    assert weights['espn_fg_under_40']==3
    items[0]['points']=5
    assert 'espn_stat_93' in player_scoring(league,'TE')[1]

def test_explicit_zero_rare_categories_need_complete_pbp_schema():
    end={'game_id':'g','play_id':'1','desc':'END GAME','total_home_score':'7','total_away_score':'3'}
    assert special_teams([end])[1]=={}
    assert parse({'fg_made_0_19':'1','fg_made_20_29':'2','fg_made_30_39':'3'})['fantasy_fg_under_40']==6

def test_espn_matchup_identity_and_exact_actual_week():
    from src.ingest.espn_fantasy import _parse_matchups
    payload={'schedule':[{'id':1,'matchupPeriodId':2,'home':{'teamId':1},'away':{'teamId':2}},
        {'id':2,'matchupPeriodId':2,'home':{'teamId':3},'away':{'teamId':4}}],
        'teams':[{'id':1,'roster':{'entries':[{'playerPoolEntry':{'player':{'id':99,'stats':[
            {'statSourceId':0,'scoringPeriodId':2,'appliedTotal':10},
            {'statSourceId':1,'scoringPeriodId':2,'appliedTotal':20}]}}}]}}]}
    rows=_parse_matchups(payload,2,{})
    assert rows[0]['matchup_id']!=rows[2]['matchup_id']
    assert rows[0]['players_points']=={'99':10}
    assert rows[1]['players_points']=={}
