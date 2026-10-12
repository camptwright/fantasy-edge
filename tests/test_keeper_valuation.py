from copy import deepcopy
import pytest
from src.services.keeper_valuation import value_scenario


def evidence():
    return dict(league_id='l', player_id='p', cost_round=5, draft_season=2026,
                season=2027, unit='lineup_points_above_replacement',
                scoring_basis='league scoring v1', horizon='full regular fantasy season',
                source='owner supplied sensitivity scenario',
                keeper=dict(low=50, base=70, high=90), pick=dict(low=20, base=30, high=40))


def test_opportunity_cost_and_bounds():
    r=value_scenario('l','p',5,evidence())
    assert r['surplus']==dict(low=10,base=40,high=70)
    assert r['break_even_keeper_value']==30
    assert r['interpretation']=='keeper_positive_across_range'
    assert r['actionable'] is False


@pytest.mark.parametrize('key,value', [('season',2026),('cost_round',4),('league_id','other'),
    ('player_id','other'),('unit','trade_value'),('source',''),('keeper',{'low':0,'base':float('nan'),'high':20}),
    ('pick',{'low':20,'base':10,'high':30}),('keeper',{'low':False,'base':1,'high':2})])
def test_rejects_unbound_or_incomparable_evidence(key,value):
    e=evidence();e[key]=value
    r=value_scenario('l','p',5,e)
    assert r['status']=='withheld' and 'surplus' not in r


def test_no_mutation_and_negative_or_uncertain_surplus():
    e=evidence();original=deepcopy(e)
    value_scenario('l','p',5,e)
    assert e==original
    e['keeper']=dict(low=0,base=10,high=15)
    assert value_scenario('l','p',5,e)['interpretation']=='pick_positive_across_range'
    e['keeper']=dict(low=10,base=30,high=50)
    assert value_scenario('l','p',5,e)['interpretation']=='sensitive_to_assumptions'


def test_missing_values_never_imputed():
    assert value_scenario('l','p',5,None)['status']=='withheld'


def test_oversized_integer_is_withheld_without_overflow():
    e=evidence()
    e['keeper']=dict(low=0,base=10**1000,high=10**1001)
    assert value_scenario('l','p',5,e)['status']=='withheld'


def test_large_finite_inputs_cannot_emit_infinity():
    e=evidence()
    e['keeper']=dict(low=1e308,base=1e308,high=1e308)
    e['pick']=dict(low=-1e308,base=-1e308,high=-1e308)
    assert value_scenario('l','p',5,e)['blockers']==['value_range_overflow']


def test_large_integer_difference_cannot_crash():
    e=evidence()
    e['keeper']=dict(low=10**308,base=10**308,high=10**308)
    e['pick']=dict(low=-10**308,base=-10**308,high=-10**308)
    assert value_scenario('l','p',5,e)['blockers']==['value_range_overflow']


@pytest.mark.parametrize('cost', [0,-1,None,True])
def test_invalid_cost_round_is_not_a_price(cost):
    e=evidence();e['cost_round']=cost
    assert value_scenario('l','p',cost,e)['status']=='withheld'


def test_positive_scenario_does_not_override_ineligible_player():
    from src.services.keeper_rules import evaluate, LEAGUE_ID
    e=evidence();e.update(league_id=LEAGUE_ID)
    r=evaluate(LEAGUE_ID,[dict(player_id='p',draft_round=6,kept_last_year=True,
        original_drafter=True,cost_pick_available=True,valuation=e)])
    assert r['players'][0]['status']=='ineligible'
    assert r['players'][0]['valuation']['status']=='supplied_scenario'
    assert r['actionable'] is False
