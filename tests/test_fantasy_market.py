import json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from src.services.fantasy_market import cohort,key,normalize,selected
from src.services.fantasy_weekly_evidence import candidates,grade


def test_format_requires_known_supported_mode():
    league=SimpleNamespace(platform='sleeper',settings={'type':1},scoring_settings={'rec':1},roster_positions=['QB','SUPER_FLEX'])
    assert cohort(league,12) is None
    league.settings['type']=2
    assert cohort(league,12)['numQbs']=='2'
    assert cohort(league,6) is None


def test_market_cache_uses_exact_identity_and_expires(tmp_path):
    now=datetime.now(timezone.utc);params={'test':1}
    directory=tmp_path/key(params)/'snapshots';directory.mkdir(parents=True)
    rows=normalize([{'player':{'id':1,'sleeperId':'abc'},'value':42}])
    (directory/'snapshot.json').write_text(json.dumps({'captured_at':now.isoformat(),'format':params,'sha256':'test','rows':rows}))
    result=selected(params,'sleeper',['abc','unknown'],now=now,archive_root=tmp_path)
    assert [p['value'] for p in result['players']]==[42,None]
    assert selected(params,'sleeper',['abc'],now=now+timedelta(days=3),archive_root=tmp_path)['status']=='stale'
    with pytest.raises(ValueError):normalize([{'player':{'id':1},'value':float('nan')}])


@pytest.mark.parametrize('position',['RB','K','DST'])
def test_provider_weekly_forecast_does_not_require_history(position):
    now=datetime.now(timezone.utc);kickoff=now+timedelta(hours=12)
    lab={'status':'candidate','coverage':{'stale_inputs':False},'league_id':'L','scoring_settings':{},'players':[{
        'player_id':'p','position':position,'weekly_evidence':{'status':'pregame_provider_projection','points':0,'week':2,'observed_at':now.isoformat()},
        'next_games':[{'id':'g','week':2,'kickoff':kickoff.isoformat()}]}]}
    records=candidates(lab,now)
    assert len(records)==1 and not records[0]['serving_promoted']
    assert not candidates(lab,kickoff)
    game=SimpleNamespace(status='final',game_time=kickoff)
    snapshot=SimpleNamespace(synced_at=kickoff+timedelta(hours=25),payload=[{'players_points':{'p':0}}])
    assert grade(records[0],game,snapshot)['absolute_error']==0
    snapshot.synced_at=kickoff
    assert grade(records[0],game,snapshot)['status']=='missing_final_platform_points'


@pytest.mark.parametrize('rows,reason',[
    ([], 'player_absent_from_platform_results'),
    ([None], 'nonfinite_platform_points'),
    ([True], 'nonfinite_platform_points'),
    ([float('nan')], 'nonfinite_platform_points'),
    ([1,2], 'conflicting_platform_points'),
])
def test_provider_result_blockers_are_distinct(rows,reason):
    now=datetime.now(timezone.utc)
    record={'id':'f','league_id':'L','position':'RB','player_id':'p','week':2,
            'game_id':'g','captured_at':(now-timedelta(days=3)).isoformat(),
            'prediction':{'points':10}}
    game=SimpleNamespace(status='final',game_time=now-timedelta(days=2))
    snapshot=SimpleNamespace(synced_at=now,payload=[{'players_points':{'p':v}} for v in rows])
    result=grade(record,game,snapshot)
    assert result['status']=='missing_or_conflicting_platform_points'
    assert result['result_blocker']==reason
    assert result['player_id']=='p' and result['week']==2 and result['game_id']=='g'
    assert 'actual' not in result
    snapshot.payload=[{'players_points':{'p':0}},{'players_points':{'p':0}}]
    assert grade(record,game,snapshot)['actual']==0
