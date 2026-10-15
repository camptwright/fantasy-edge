from src.api.routers.workspace import Overview, PlayerDetail, EngineWeek
from src.services.workspace_view_response import trim
import pytest
from fastapi import Response, HTTPException


def sample():
    return Overview(league_id='L', status='snapshot_available', message='Current checkpoint',
        roster_players=[PlayerDetail(player_id='mine',name='Mine',engine_weeks=[EngineWeek(week=6,points=12,environment='research')])],
        comparison_players=[PlayerDetail(player_id='mine',name='Mine',history_status='complete'),
                            PlayerDetail(player_id='other',name='Other',history_status='complete')])


def test_tool_views_do_not_send_unrelated_large_sections():
    result=trim(sample(),'trade')
    assert 'roster_players' not in result
    assert 'outcomes' not in result
    assert 'history_status' not in result['comparison_players'][0]
    assert result['comparison_players'][0]['player_id']=='mine'


def test_roster_retains_weekly_evidence_and_selected_profile_is_complete():
    result=trim(sample(),'overview')
    assert result['roster_players'][0]['engine_weeks'][0]['points']==12
    selected=trim(sample(),'player',['other'])
    assert [p['player_id'] for p in selected['comparison_players']]==['other']
    assert selected['comparison_players'][0]['history_status']=='complete'


def test_compared_players_receive_details_without_enlarging_rest_of_catalog():
    result=trim(sample(),'players',['mine'])
    assert result['comparison_players'][0]['history_status']=='complete'
    assert 'history_status' not in result['comparison_players'][1]


def test_journal_receives_ownership_and_frozen_checkpoint_context():
    result=trim(sample(),'journal')
    assert result['league_id']=='L'
    assert result['roster_players'][0]['player_id']=='mine'


@pytest.mark.asyncio
async def test_lazy_player_detail_is_bound_to_catalog_checkpoint(monkeypatch):
    from src.api.routers import workspace
    async def view(*args,**kwargs):
        return {'status':'snapshot_available','generated_at':'new-checkpoint',
                'comparison_players':[{'player_id':'a','name':'A'}]}
    monkeypatch.setattr(workspace,'league_view',view)
    with pytest.raises(HTTPException) as error:
        await workspace.detailed_player('L','a',Response(),generated_at='old-checkpoint',db=None)
    assert error.value.status_code==409
    result=await workspace.detailed_player('L','a',Response(),generated_at='new-checkpoint',db=None)
    assert result.player_id=='a'
