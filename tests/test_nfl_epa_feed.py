from datetime import datetime,timezone,timedelta
from src.services.nfl_epa_feed import features_for,number


def test_epa_features_exclude_unavailable_current_and_duplicate_games():
    now=datetime.now(timezone.utc)
    rows=[{'team':'KC','game_id':str(i),'kickoff':(now-timedelta(days=i+1)).isoformat(),
        'observed_at':now.isoformat(),'passing_epa':2,'rushing_epa':1,'offensive_epa':3} for i in range(8)]
    result=features_for(rows+rows,'KC',now)
    assert result['games']==8 and result['offensive_epa']==3
    assert features_for(rows,'KC',now-timedelta(seconds=1))['status']=='insufficient_history'
    assert number('nan') is None and number('') is None and number('-2.5')==-2.5
