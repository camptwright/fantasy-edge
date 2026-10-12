from datetime import datetime,timezone,timedelta
from src.services.research_shadow_ledger import observation
from src.services.research_shadow_ledger import close
from src.services.forecast_evidence import save,payloads
from src.models.facts import Game,TeamMarketLine
from types import SimpleNamespace


async def test_shadow_close_uses_database_when_entry_archive_is_missing(db,tmp_path,monkeypatch):
    import src.services.research_shadow_ledger as ledger
    monkeypatch.setattr(ledger,'get_settings',lambda:SimpleNamespace(raw_archive_dir=str(tmp_path)))
    now=datetime.now(timezone.utc);kickoff=now-timedelta(hours=1)
    game=Game(sport='nfl',season=2026,status='final',game_time=kickoff)
    db.add(game);await db.flush()
    quote=TeamMarketLine(game_id=game.id,source='test',market='moneyline',side='home',
        price_american=110,line=None,line_type='current',observed_at=kickoff-timedelta(minutes=5))
    db.add(quote);await db.flush()
    terms={'game_id':str(game.id),'kind':'team','book':'test','market':'moneyline','side':'home','line':None}
    entry=observation(terms,.6,'v',kickoff-timedelta(hours=2),kickoff,['research'])
    await save(db,'shadow_entries',entry);await db.commit()
    first=await close(db)
    assert first['captured']==1
    assert (await close(db))['captured']==0
    rows=[r async for r in payloads(db,'shadow_closes')]
    assert len(rows)==1 and rows[0]['clv_percent'] is None and rows[0]['actionable'] is False


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
