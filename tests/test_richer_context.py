import json
from datetime import datetime,timedelta,timezone
import pytest
from src.services.weather_evidence import features,FIELDS
from src.services.news_evidence import headlines_for_players
from src.services.scorer_evaluation import distribution_score,evaluate

NOW=datetime(2026,9,15,12,tzinfo=timezone.utc)


def weather():
    return {'utc_offset_seconds':0,'hourly_units':FIELDS.copy(),'hourly':{
        'time':[(NOW+timedelta(hours=i)).replace(tzinfo=None).isoformat() for i in range(1,5)],
        **{k:[10]*4 for k in FIELDS}}}


def test_weather_units_temporal_and_roof_guards():
    args=dict(captured_at=NOW-timedelta(minutes=10),as_of=NOW,kickoff=NOW+timedelta(hours=1),roof='outdoor')
    assert features(weather(),**args)['status']=='forecast_context'
    assert features(weather(),**dict(args,roof='closed'))['hours']==[]
    assert not features(weather(),**dict(args,roof='retractable_unknown'))['exposure_confirmed']
    assert features(weather(),**dict(args,captured_at=NOW+timedelta(minutes=1)))['status']=='unavailable_or_stale_at_prediction'
    payload=weather();payload['hourly_units']['wind_speed_10m']='mph'
    assert features(payload,**args)['status']=='unsupported_units_or_timezone'
    payload=weather();payload['hourly']['wind_gusts_10m'][0]=None
    assert features(payload,**args)['status']=='incomplete_forecast'
    payload=weather();payload['hourly']['wind_gusts_10m']=None
    assert features(payload,**args)['status']=='malformed_hourly_series'
    assert features(None,**args)['status']=='malformed_forecast'


def test_news_old_publication_and_partial_names_excluded(tmp_path):
    rows=[{'title':t,'url':f'https://example/{i}','observed_at':NOW.isoformat(),'published_at_raw':p}
        for i,(t,p) in enumerate([('Josh Allen practices',''),('Josh Allenson practices',''),
            ('Josh Allen old injury','Mon, 01 Sep 2025 10:00:00 GMT')])]
    (tmp_path/'news.json').write_text(json.dumps(rows))
    assert len(headlines_for_players(tmp_path,{'p':'Josh Allen'},NOW)['p'])==1


def test_joint_scorer_evaluation_includes_none_and_other():
    p={'player':.5,'__other__':.3,'__none__':.2}
    assert distribution_score(p,'player')['multiclass_brier']==pytest.approx(.38)
    with pytest.raises(ValueError):distribution_score({'player':1},'player')
    row=dict(game_id='g',market='first_td_scorer',captured_at=NOW,kickoff=NOW+timedelta(hours=1),
        training_available_at=NOW-timedelta(days=1),validated_final=True,pending_correction=False,
        baseline=p,candidate=p,outcome='__none__')
    assert evaluate([row])['metrics'][0]['log_loss_delta']==0
    assert len(evaluate([dict(row,pending_correction=True)])['excluded'])==1
    with pytest.raises(ValueError):evaluate([row,row])
