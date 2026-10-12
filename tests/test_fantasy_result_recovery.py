from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from src.services.fantasy_result_recovery import recover
from src.services.fantasy_score_history import scoring_hash
from src.services.fantasy_component_history import ARCHIVE_ID,PREFIX


def evidence():
    kickoff=datetime(2026,9,10,tzinfo=timezone.utc)
    scoring={'rec':1}
    record={'id':'r','version':'v','league_id':'l','scoring_cohort':'s','game_id':'g',
        'platform_player_id':'p','captured_at':(kickoff-timedelta(days=1)).isoformat(),
        'scoring_settings':scoring,'prediction':{'status':'candidate','scoring_weights':{'receptions':1},
        'baseline_subtotal':4,'modeled_subtotal':5}}
    game=NS(id='g',week=1,season=2026,status='final',game_time=kickoff)
    players={str(i):{'position':'WR','game_id':'g','stats':{'gp':1,'rec':2}} for i in range(8)}
    players['p']={'position':'WR','game_id':'g','stats':{'gp':1}}
    archive=NS(league_id=ARCHIVE_ID,kind=PREFIX+'2026',week=1,synced_at=kickoff+timedelta(days=2),
        payload={'schema_version':1,'season':2026,'week':1,'players':players})
    official=NS(league_id='l',kind='scored_history',week=1,synced_at=archive.synced_at,
        payload={'schema_version':1,'game_ids':['g'],'season':'2026','week':1,'scoring_contract':scoring,'scoring_hash':scoring_hash(scoring),
                 'points':{str(i):2 for i in range(8)}})
    return record,game,archive,official


def test_zero_requires_played_exact_game_and_reconciled_position():
    args=evidence();result=recover(*args,identity_matches=True)
    assert result['status']=='graded' and result['actual']==0
    assert result['candidate_error']==5 and result['reconciliation_samples']==8
    assert args[0]['prediction']['modeled_subtotal']==5


def test_absence_and_identity_mismatch_never_infer_zero():
    args=evidence();assert recover(*args)['status']=='withheld'
    args[2].payload['players'].pop('p')
    assert recover(*args,identity_matches=True)['reason']=='missing_exact_player_game'


def test_disagreement_or_wrong_frozen_weights_withholds():
    args=evidence();args[3].payload['points']['0']=99
    assert recover(*args,identity_matches=True)['reason']=='insufficient_position_reconciliation'
    args=evidence();args[0]['prediction']['scoring_weights']['receptions']=2
    assert recover(*args,identity_matches=True)['reason']=='frozen_component_mapping_mismatch'


def test_existing_canonical_components_cannot_be_overwritten():
    assert recover(*evidence(),identity_matches=True,existing_values={'receptions':5})['reason']=='conflicting_existing_component'
    assert recover(*evidence(),identity_matches=True,existing_values={'receptions':0})['status']=='graded'


@pytest.mark.parametrize('which,field,value,reason',[
    (2,'schema_version',None,'unsupported_result_schema'),
    (3,'schema_version',True,'unsupported_result_schema'),
    (3,'game_ids',[],'official_game_binding_mismatch'),
    (3,'game_ids','g','official_game_binding_mismatch')])
def test_fallback_requires_supported_bound_archive(which,field,value,reason):
    args=evidence();args[which].payload[field]=value
    assert recover(*args,identity_matches=True)['reason']==reason


@pytest.mark.asyncio
async def test_ros_recovery_rebinds_copy_and_preserves_pending_corrections():
    from src.services.fantasy_prospective import grade_ros_parts,grade_with_recovery,grade
    r,game,archive,official=evidence()
    r.update(player_id='canonical',remaining_schedule=[{'id':'g'}])
    identities={'p':NS(id='canonical')}
    snapshots={(ARCHIVE_ID,1,PREFIX+'2026'):archive,('l',1,'scored_history'):official}
    db=AsyncMock()
    single=await grade_with_recovery(db,r,game,{},False,identities,snapshots)
    ros={**r,'game_id':'first_game'};original=deepcopy(ros)
    parts=await grade_ros_parts(db,ros,{'g':game},{},set(),identities,snapshots)
    assert parts==[single] and single['status']=='graded'
    assert ros==original
    blocked=await grade_ros_parts(db,ros,{'g':game},{},{('g','canonical')},identities,snapshots)
    assert blocked[0]['status']=='pending_correction'
    assert grade(ros,game,{'receptions':0})['status']=='game_binding_mismatch'
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_ros_later_games_still_require_original_pregame_capture_and_identity():
    from src.services.fantasy_prospective import grade_ros_parts
    r,game,archive,official=evidence()
    r.update(player_id='canonical',remaining_schedule=[{'id':'g'}])
    snapshots={(ARCHIVE_ID,1,PREFIX+'2026'):archive,('l',1,'scored_history'):official}
    db=AsyncMock()
    parts=await grade_ros_parts(db,r,{'g':game},{},set(),{},snapshots)
    assert parts[0]['recovery_blocker']=='unverified_platform_identity'
    r['captured_at']=(game.game_time+timedelta(seconds=1)).isoformat()
    parts=await grade_ros_parts(db,r,{'g':game},{},set(),{'p':NS(id='canonical')},snapshots)
    assert parts[0]['status']=='invalid_capture_time'
