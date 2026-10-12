import pytest
from pydantic import ValidationError
from src.services.keeper_rules import evaluate, LEAGUE_ID
from src.api.routers.workspace import KeeperPlayerInput


def player(**changes):
    return dict(player_id='p',draft_round=6,kept_last_year=False,
                original_drafter=True,cost_pick_available=True,**changes)


def test_sixth_costs_fifth_and_second_costs_first():
    p=player()
    assert evaluate(LEAGUE_ID,[p])['players'][0]['cost_round']==5
    p['draft_round']=2
    r=evaluate(LEAGUE_ID,[p])
    assert r['players'][0]['cost_round']==1
    assert r['players'][0]['status']=='eligible_under_supplied_evidence'
    assert r['actionable'] is False


@pytest.mark.parametrize('field,value,reason',[
    ('draft_round',1,'first_round_draftee_ineligible'),
    ('kept_last_year',True,'consecutive_year_keeper_ineligible'),
    ('draft_round',None,'missing_or_invalid_draft_round'),
    ('kept_last_year',None,'previous_keeper_status_unknown'),
    ('original_drafter',False,'original_draft_cost_basis_unconfirmed'),
    ('cost_pick_available',False,'cost_pick_availability_unconfirmed')])
def test_rules_and_missing_evidence(field,value,reason):
    p=player();p[field]=value
    assert reason in evaluate(LEAGUE_ID,[p])['players'][0]['blockers']


def test_maximum_duplicates_and_league_scope():
    assert evaluate(LEAGUE_ID,[player(),player()])['selection_blockers']==['one_keeper_maximum','duplicate_player']
    assert evaluate('other',[player()])['status']=='unconfigured_league'


def test_input_rejects_boolean_round_and_string_boolean():
    for changed in ({'draft_round':True},{'kept_last_year':'false'}):
        with pytest.raises(ValidationError): KeeperPlayerInput(**{**player(),**changed})
