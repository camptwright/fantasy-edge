from src.services.custom_projection import exact_projected_points
from src.services.missing_result_queue import classify

def test_exact_identity_not_display_name():
    averages={'123':{'passing_yards':200}}
    assert exact_projected_points({'pass_yd':.04},'123',averages,'QB')==8
    assert exact_projected_points({'pass_yd':.04},'Player Name',averages,'QB') is None

def test_missing_component_is_not_zero():
    assert exact_projected_points({'pass_yd':.04,'pass_td':4},'123',{'123':{'passing_yards':200}},'QB') is None
    assert exact_projected_points({'pass_td':4},'123',{'123':{'passing_touchdowns':0}},'QB')==0

def test_queue_states():
    assert classify('final',False,False,False)=='missing_player_results'
    assert classify('final',True,False,False)=='missing_stat_category'
    assert classify('final',True,True,True)=='pending_correction'
    assert classify('scheduled',False,False,False)=='awaiting_final'
    assert classify('final',True,True,False)=='resolved'
    assert classify('cancelled',False,False,False)=='event_status_review'


def test_fantasy_queue_expands_actual_frozen_weights_and_deduplicates():
    from src.services.missing_result_queue import add_fantasy_records
    rows={}
    forecast={'game_id':'g','player_id':'p','captured_at':'2026-09-02T00:00:00+00:00',
              'prediction':{'scoring_weights':{'receptions':1,'fumbles_lost':-2}}}
    add_fantasy_records(rows,[forecast,{**forecast,'captured_at':'2026-09-01T00:00:00+00:00'}])
    assert len(rows)==2
    assert all(r['sources']==['fantasy_prospective'] for r in rows.values())
    assert all(r['captured_at'].startswith('2026-09-01') for r in rows.values())


def test_external_namespace_fail_closed():
    import asyncio
    import pytest
    from src.services.player_identity import resolve_external_players
    with pytest.raises(ValueError):
        asyncio.run(resolve_external_players(None,'ncaaf','espn_nfl',['123']))
