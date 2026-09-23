from datetime import datetime,timezone,timedelta
from src.services.research_shadow_ledger import observation


def test_shadow_identity_excludes_price_and_never_places_a_bet():
    now=datetime.now(timezone.utc);kickoff=now+timedelta(hours=1)
    terms={'game_id':'g','kind':'player','player_id':'p','market':'yards','side':'over','line':3.5,'book':'x','price_american':110,'quote_id':'a'}
    a=observation(terms,.6,'v',now,kickoff,['roster_unverified'])
    b=observation({**terms,'price_american':120,'quote_id':'b'},.6,'v',now,kickoff,[])
    assert a['id']==b['id'] and a['actionable'] is False and a['stake'] is None
    assert a['blockers']==['roster_unverified'] and not a['exposure']
    assert not observation(terms,.6,'v',kickoff,kickoff,[])
    assert not observation(terms,float('nan'),'v',now,kickoff,[])
    assert a['id']!=observation(terms,.6,'v2',now,kickoff,[])['id']
