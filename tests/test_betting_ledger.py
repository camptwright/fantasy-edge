from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from src.models.base import utcnow
from src.models.facts import Game, TeamMarketLine
from src.models.ledger import LedgerEvent
from src.api.routers.ledger import Entry, Settlement, Policy, policy, record, settle, summary
from src.services.betting_ledger import exposure, check_limits, capture_closes


def entry(**kw):
    return Entry(**dict(dict(request_id=uuid4().hex, mode='paper', currency='USD', stake='10.00',
        placed_at=utcnow()-timedelta(hours=2), game_id=uuid4(), kind='team', market='moneyline',
        side='home', price_american=-110, book='testbook', settlement_rules='Test receipt rules'), **kw))


@pytest.mark.parametrize('kw', [dict(stake='0'),dict(stake='1.001'),dict(price_american=0),
    dict(side='over'),dict(line='2'),dict(kind='player'),dict(currency='usd'),
    dict(placed_at=utcnow()+timedelta(days=1)),dict(line='NaN')])
def test_invalid_terms(kw):
    with pytest.raises(ValidationError):
        entry(**kw)


def test_gross_exposure_and_limits():
    terms={'sport':'nfl','book':'test','player_id':'p'}
    bets=[SimpleNamespace(id='a',currency='USD',mode='actual',stake=Decimal('10.25'),game_id='g',terms=terms),
          SimpleNamespace(id='b',currency='USD',mode='actual',stake=Decimal('5.25'),game_id='g',terms=terms),
          SimpleNamespace(id='c',currency='USD',mode='paper',stake=Decimal('100'),game_id='g',terms=terms)]
    gross=exposure(bets,{},'USD')
    assert gross['gross']=='15.50' and gross['game']['g']=='15.50'
    assert exposure(bets,{'a':{'status':'void'}},'USD')['gross']=='5.25'
    assert check_limits(gross,dict(terms,game_id='g'),Decimal('1'),{})['status']=='unconfigured'
    assert check_limits(gross,dict(terms,game_id='g'),Decimal('1'),{'game':'16'})['status']=='blocked'
    assert check_limits(gross,terms,Decimal('1'),{'total':'16.50'})['status']=='within_configured_limits'


@pytest.mark.asyncio
async def test_record_corrections_idempotency_and_close(db):
    # Isolated test database only; policies are independent of fixture game cascades.
    await db.execute(text('DELETE FROM ledger_policies'))
    game=Game(sport='nfl',season=2026,game_time=utcnow()-timedelta(hours=1),status='final')
    db.add(game)
    await db.flush()
    req=entry(game_id=game.id)
    first=await record(req,db)
    assert (await record(req,db))['created'] is False
    with pytest.raises(HTTPException) as exc:
        await record(req.model_copy(update={'stake':Decimal('11')}),db)
    assert exc.value.status_code==409
    from uuid import UUID
    bet_id=UUID(first['id'])
    win=Settlement(request_id=uuid4().hex,status='won',returned='19.09',evidence='test receipt')
    await settle(bet_id,win,db)
    assert (await settle(bet_id,win,db))['created'] is False
    assert (await summary(db))['items'][0]['settlement']['profit']=='9.09'
    await settle(bet_id,Settlement(request_id=uuid4().hex,status='open',returned='0',evidence='book review'),db)
    assert (await summary(db))['exposure']['USD']['paper']['gross']=='10.00'
    assert (await capture_closes(db))['captured']==1
    assert (await capture_closes(db))['captured']==0
    db.add(TeamMarketLine(game_id=game.id,market='moneyline',side='home',line=None,price_american=-120,
                         source='testbook',line_type='live',observed_at=game.game_time-timedelta(minutes=4)))
    # A more recent post-start quote must never become the closing proxy.
    db.add(TeamMarketLine(game_id=game.id,market='moneyline',side='home',line=None,price_american=180,
                         source='testbook',line_type='live',observed_at=game.game_time+timedelta(minutes=1)))
    await db.commit()
    assert (await capture_closes(db))['captured']==1
    closing=(await summary(db))['items'][0]['closing']
    assert closing['price_american']==-120 and closing['clv_percent'] is None
    assert (await capture_closes(db))['captured']==0
    assert len((await db.scalars(select(LedgerEvent).where(LedgerEvent.bet_id==bet_id))).all())==4


@pytest.mark.asyncio
async def test_limits_block_paper_but_preserve_actual_history(db):
    await db.execute(text('DELETE FROM ledger_policies'))
    game=Game(sport='nfl',season=2026,game_time=None)
    db.add(game)
    await db.flush()
    await policy(Policy(currency='USD',total='5'),db)
    with pytest.raises(HTTPException) as exc:
        await record(entry(game_id=game.id),db)
    assert exc.value.status_code==409
    result=await record(entry(game_id=game.id,mode='actual'),db)
    assert result['risk']['status']=='blocked'
    assert (await capture_closes(db))['captured']==0
    assert (await summary(db))['exposure']['USD']['actual']['gross']=='10.00'
    await policy(Policy(currency='USD'),db)
    assert (await summary(db))['policies']['USD']=={}
