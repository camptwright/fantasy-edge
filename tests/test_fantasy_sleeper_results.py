from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
import hashlib
import json
from src.services.fantasy_sleeper_results import grade_components
from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX
from src.services.fantasy_score_history import scoring_hash


def test_exact_reconciled_components_and_fail_closed():
    now=datetime.now(timezone.utc);scoring={'rec':1}
    record=dict(id='f',league_id='L',position='WR',player_id='target',game_id='g',week=2,
        captured_at=(now-timedelta(days=4)).isoformat(),prediction={'points':5},
        scoring_hash=hashlib.sha256(json.dumps(scoring,sort_keys=True).encode()).hexdigest())
    game=NS(id='g',season=2026,week=2,status='final',game_time=now-timedelta(days=3))
    rows={str(i):dict(position='WR',stats={'gp':1,'rec':i},game_id='g') for i in range(8)}
    rows['target']=dict(position='WR',stats={'gp':1,'rec':0},game_id='g')
    archive=NS(league_id=ARCHIVE_ID,kind=PREFIX+'2026',week=2,synced_at=now,
               payload=dict(schema_version=1,season=2026,week=2,players=rows))
    official=NS(league_id='L',kind='scored_history',week=2,synced_at=now,
        payload=dict(schema_version=1,game_ids=['g'],season='2026',week=2,scoring_contract=scoring,scoring_hash=scoring_hash(scoring),points={str(i):i for i in range(8)}))
    assert grade_components(record,game,archive,official)['actual']==0
    from src.services.fantasy_sleeper_results import recover_lineup_points
    frozen={**record,'lineups':{'opponent_starters':['0'],'games':[{'id':'g'}]},
        'lineup_experiment':{'scoring_hash':scoring_hash(scoring),'simulation':{
            'current':{'player_ids':['target']},'candidate':{'player_ids':['target']}}}}
    recovered,audit=recover_lineup_points(frozen,official,archive,{'g':game})
    assert recovered['target']==0 and 'target' in audit['recovered']
    assert 'target' not in official.payload['points']
    frozen['lineups']['games']=[]
    recovered,audit=recover_lineup_points(frozen,official,archive,{'g':game})
    assert 'target' not in recovered
    assert audit['blocked']['target']=='missing_frozen_game_binding'
    official.payload['points']['0']=99
    assert grade_components(record,game,archive,official)['result_blocker']=='insufficient_position_reconciliation'
    official.payload['points']['0']=0
    rows['target']['game_id']='other'
    assert grade_components(record,game,archive,official)['result_blocker']=='missing_exact_player_game'
    rows['target']['game_id']='g';rows['target']['stats']['gp']=0
    assert grade_components(record,game,archive,official)['result_blocker']=='unsupported_or_incomplete_scoring'
    assert grade_components({**record,'scoring_hash':'changed'},game,archive,official)['result_blocker']=='scoring_rules_mismatch'
