from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from src.services.fantasy_weekly_evidence import grade_archive
from src.services.fantasy_weekly_evidence import grade
from src.services.fantasy_score_history import scoring_hash


def test_archive_requires_exact_frozen_contract_and_finality():
    now=datetime.now(timezone.utc)
    contract={'scoring':{'x':1},'official_rules':{'items':[1]}}
    digest=scoring_hash(contract['scoring'],contract['official_rules'])
    record=dict(id='f',league_id='espn:1',position='K',game_id='g',week=2,player_id='p',
                captured_at=(now-timedelta(days=4)).isoformat(),scoring_contract_hash=digest,prediction={'points':3})
    game=NS(id='g',week=2,season=2026,status='final',game_time=now-timedelta(days=3))
    payload=dict(week=2,season='2026',game_ids=['g'],status='reconciled',overlap_players=10,
                 conflicting_player_ids=[],scoring_hash=digest,points={'p':0},scoring_contract=contract,
                 schema_version=1,source='espn_league_historical_player_pool')
    snapshot=NS(league_id='espn:1',week=2,synced_at=now,payload=payload,kind='historical_player_scores')
    assert grade(record,game,NS(synced_at=now,payload=[{'players_points':{'p':0}}]))['result_blocker']=='requires_rule_bound_archive'
    assert grade_archive(record,game,snapshot)['absolute_error']==3
    assert grade_archive({**record,'scoring_contract_hash':None},game,snapshot)['result_blocker']=='missing_frozen_scoring_contract'
    for field,value in [('scoring_hash','changed'),('scoring_contract',{}),('schema_version',2),('source','unknown'),('season','2025'),('game_ids',[]),('overlap_players',9),('points',{}),('conflicting_player_ids',['p'])]:
        snapshot.payload={**payload,field:value}
        assert grade_archive(record,game,snapshot)['status']=='historical_result_withheld'
    snapshot.payload=payload
    snapshot.synced_at=game.game_time
    assert grade_archive(record,game,snapshot)['result_blocker']=='awaiting_final_snapshot'
