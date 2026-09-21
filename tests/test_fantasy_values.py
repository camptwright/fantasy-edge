from copy import deepcopy
from src.services.fantasy_values import value_board,compare,suggestions


def player(pid,pos,value,owner=None):
    return {'player_id':pid,'name':pid,'position':pos,'roster_ids':[owner] if owner else [],
            'injury_status':None,'ros':{'full_ros_value':value*16 if value is not None else None,
            'per_game':{'status':'candidate' if value is not None else 'insufficient_history','per_game':value}}}


def data():
    return {'status':'candidate','coverage':{'stale_inputs':False},'roster_positions':['RB','WR','BN'],
            'players':[player('ar','RB',20,1),player('ard','RB',18,1),player('aw','WR',8,1),
                       player('br','RB',8,2),player('bw','WR',20,2),player('bwd','WR',18,2),
                       player('free','RB',6),player('unknown','WR',None)],
            'rosters':[{'roster_id':1,'name':'A','is_mine':True,'player_ids':['ar','ard','aw']},
                       {'roster_id':2,'name':'B','is_mine':False,'player_ids':['br','bw','bwd']}]}


def test_values_do_not_invent_market_prices_or_missing_history():
    board=value_board(data());p={p['player_id']:p for p in board['players']}
    assert p['ar']['value']['above_available_replacement_per_game']==14
    assert p['aw']['value']['above_available_replacement_per_game'] is None
    assert p['unknown']['value']['conditional_points_per_game'] is None
    assert all(p['value']['market_price'] is None for p in board['players'])


def test_both_rosters_benefit_without_summing_bench_points():
    r=compare(data(),['ard'],['bwd'])
    assert r['status']=='research_candidate' and r['verdict'] is None
    assert r['side_a']['conditional_lineup_gain']==10
    assert r['side_b']['conditional_lineup_gain']==10
    assert suggestions(data())


def test_invalid_ownership_duplicates_and_uneven_deals_abstain():
    assert compare(data(),['ar'],['ar'])['status']=='withheld'
    assert compare(data(),['missing'],['bw'])['blockers']==['unknown_player']
    assert 'packages_must_belong_to_two_distinct_rosters' in compare(data(),['ar'],['aw'])['blockers']
    assert 'uneven_trade_requires_explicit_add_drop_plan' in compare(data(),['ar','ard'],['bwd'])['blockers']


def test_injuries_staleness_and_unknown_bench_do_not_support_recommendations():
    d=data();d['coverage']['stale_inputs']=True
    assert not suggestions(d) and compare(d,['ard'],['bwd'])['status']=='withheld'
    d=data();d['players'][0]['injury_status']='Out'
    assert not suggestions(d)
    d=data();d['rosters'][0]['player_ids'].append('unknown')
    assert compare(d,['ard'],['bwd'])['side_a']['conditional_lineup_gain'] is None


def test_superflex_reoptimizes_and_unsupported_slots_abstain():
    d=data();d['roster_positions']=['SUPER_FLEX','FLEX','BN']
    r=compare(d,['ard'],['bwd'])
    assert r['side_a']['conditional_lineup_gain']==0
    d['roster_positions']=['DL']
    assert 'unsupported_starting_slots' in compare(d,['ard'],['bwd'])['blockers']


def test_deterministic_pure_board():
    d=data();original=deepcopy(d)
    assert value_board(d)==value_board(d)
    assert d==original


def test_active_label_is_not_an_injury():
    d=data()
    for p in d['players']:p['injury_status']='ACTIVE'
    assert compare(d,['ard'],['bwd'])['status']=='research_candidate'


def test_confirmed_source_precedence_is_value_specific():
    from types import SimpleNamespace
    from src.ingest.fantasy_scoring import preserve_confirmed_boxscore
    fact=SimpleNamespace(id='stat',value=5)
    assert preserve_confirmed_boxscore(fact,{'stat':5})
    assert not preserve_confirmed_boxscore(fact,{'stat':4})
    assert not preserve_confirmed_boxscore(fact,{})


def test_uneven_trade_requires_balanced_explicit_roster_adjustments():
    result=compare(data(),['ar','ard'],['bw'],adjustments={'a':{'add':['free'],'drop':[]},'b':{'add':[],'drop':['br']}})
    assert result['status']=='research_candidate'
    invalid=compare(data(),['ar','ard'],['bw'],adjustments={'a':{'add':['br'],'drop':[]},'b':{'add':[],'drop':['br']}})
    assert invalid['status']=='withheld'
