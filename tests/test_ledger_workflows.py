import hashlib
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4, UUID
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text
from src.models.base import utcnow
from src.models.facts import Game, TeamMarketLine, QuoteAvailability, PlayerPropLine
from src.models.identity import Player
from src.models.ledger import LedgerBet, LedgerEvent
from src.api.routers.ledger import Entry, record
from src.api.routers.ledger_imports import ImportBatch, preview_receipts, commit_receipts
from src.services.ledger_quotes import resolve_quote
from src.services.ledger_rules import verify_close


def receipt(game_id, **overrides):
    data={'receipt_id':'receipt-123','account_alias':'local-test', 'entry':{'game_id':str(game_id),
        'currency':'USD','stake':'10.00','placed_at':(utcnow()-timedelta(hours=1)).isoformat(),
        'kind':'team','market':'moneyline','side':'home','line':None,'price_american':-110,
        'book':'testbook','settlement_rules':'As shown on receipt'}}
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_receipt_atomic_preview_duplicate_and_conflict(db):
    game=Game(sport='nfl',season=2026)
    db.add(game); await db.flush()
    raw=receipt(game.id)
    batch=ImportBatch(receipts=[raw])
    preview=await preview_receipts(batch,db)
    assert preview['can_commit'] and preview['rows'][0]['status']=='new'
    assert await db.scalar(select(func.count()).select_from(LedgerBet))==0
    batch.preview_sha256=preview['preview_sha256']
    assert (await commit_receipts(batch,db))['imported']==1
    assert (await commit_receipts(batch,db))['duplicates']==1
    raw['entry']['stake']='12.00'
    bad=await preview_receipts(ImportBatch(receipts=[raw]),db)
    assert not bad['can_commit']
    # One valid plus one conflicting receipt commits nothing.
    new=receipt(game.id,receipt_id='receipt-456')
    mixed=ImportBatch(receipts=[new,raw])
    mixed.preview_sha256=(await preview_receipts(mixed,db))['preview_sha256']
    with pytest.raises(HTTPException): await commit_receipts(mixed,db)
    assert await db.scalar(select(func.count()).select_from(LedgerBet))==1


@pytest.mark.asyncio
async def test_receipt_attach_existing_and_changed_preview(db):
    game=Game(sport='nfl',season=2026)
    db.add(game);await db.flush()
    raw=receipt(game.id)
    batch=ImportBatch(receipts=[raw])
    old_preview=await preview_receipts(batch,db)
    bet=await record(Entry(**raw['entry'],mode='actual',request_id=uuid4().hex),db)
    batch.preview_sha256=old_preview['preview_sha256']
    with pytest.raises(HTTPException):await commit_receipts(batch,db)
    raw['existing_bet_id']=bet['id']
    batch=ImportBatch(receipts=[raw])
    preview=await preview_receipts(batch,db)
    assert preview['rows'][0]['status']=='attach'
    batch.preview_sha256=preview['preview_sha256']
    assert (await commit_receipts(batch,db))['imported']==1
    assert await db.scalar(select(func.count()).select_from(LedgerBet))==1


@pytest.mark.asyncio
async def test_quote_draft_exact_identity_stale_paper_and_actual_price(db):
    await db.execute(text('DELETE FROM ledger_policies'))
    game=Game(sport='nfl',season=2026,game_time=utcnow()+timedelta(hours=2),status='scheduled')
    player=Player(sport='nfl',full_name='Test Player')
    db.add_all([game,player]);await db.flush()
    quote=PlayerPropLine(game_id=game.id,player_id=player.id,stat_type='receiving_yards',line=45.5,
        over_price_american=-110,under_price_american=-120,source='testbook',observed_at=utcnow()-timedelta(minutes=1))
    db.add(quote);await db.flush()
    draft=await resolve_quote(db,'player',quote.id,'under')
    assert draft['terms']['price_american']==-120 and draft['terms']['player_id']==str(player.id)
    entry=Entry(**draft['terms'],mode='paper',request_id=uuid4().hex,stake='10',currency='USD',placed_at=utcnow(),settlement_rules='Test')
    with pytest.raises(HTTPException):await record(entry,db)
    db.add(QuoteAvailability(kind='prop',quote_id=quote.id,source=quote.source,seen_at=utcnow(),available=True))
    await db.flush()
    assert (await record(entry,db))['created']
    actual=entry.model_copy(update={'mode':'actual','price_american':-115,'request_id':uuid4().hex})
    assert (await record(actual,db))['created']


def reviewed(**kw):
    source='Synthetic evidence for offline tests only.'
    return dict(source_snapshot=source,source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        source_url='https://example.test/rules',reviewed_by='test',reviewed_at='2026-09-14T00:00:00+00:00',**kw)


def verified_fixture():
    kickoff=utcnow()-timedelta(hours=1)
    terms=dict(game_id=str(uuid4()),kind='team',player_id=None,market='moneyline',side='home',line=None,
        book='testbook',product='sportsbook',jurisdiction='TEST',period='full_game',sport='nfl',price_american=110)
    bet=SimpleNamespace(id=uuid4(),terms=terms,placed_at=kickoff-timedelta(hours=1))
    quote=SimpleNamespace(id=uuid4(),price_american=-110,observed_at=kickoff-timedelta(seconds=1))
    contract={k:v for k,v in terms.items() if k not in ('sport','price_american')}
    rule=reviewed(book='testbook',product='sportsbook',jurisdiction='TEST',sport='nfl',market='moneyline',
        source_observed_at=(kickoff-timedelta(days=2)).isoformat(),
        source='https://example.test/rules',status='verified',unresolved=[],
        effective_from=(kickoff-timedelta(days=2)).isoformat(),effective_until=(kickoff+timedelta(days=2)).isoformat(),
        clauses={k:'test rule' for k in ('stat_definition','participation','overtime','void_conditions','push_treatment')})
    registry={'rules':{'v1':rule},'quotes':{str(quote.id):reviewed(contract=contract,rule_id='v1',
        price_american=-110,observed_at=quote.observed_at.isoformat(),designation='official_pregame_close',kickoff=kickoff.isoformat())},
        'receipts':{str(bet.id):reviewed(contract=contract,rule_id='v1',price_american=110,placed_at=bet.placed_at.isoformat())}}
    return bet,quote,kickoff,registry


def test_verified_clv_sign_and_evidence_gates():
    bet,quote,kickoff,registry=verified_fixture()
    result=verify_close(bet,quote,kickoff,registry)
    assert result['official_close'] and result['clv_percent']==10
    assert not verify_close(bet,quote,kickoff,{})['official_close']
    reg=deepcopy(registry);reg['quotes'][str(quote.id)]['designation']='last_observed'
    partial=verify_close(bet,quote,kickoff,reg)
    assert partial['rule_match'] and partial['clv_percent'] is None
    for field in ('source_sha256','price_american','kickoff','rule_id'):
        reg=deepcopy(registry);reg['quotes'][str(quote.id)][field]='wrong'
        assert not verify_close(bet,quote,kickoff,reg)['official_close']
    reg=deepcopy(registry);reg['receipts'][str(bet.id)]['contract']['jurisdiction']='OTHER'
    assert not verify_close(bet,quote,kickoff,reg)['rule_match']
    reg=deepcopy(registry);reg['rules']['v1']['effective_until']=bet.placed_at.isoformat()
    assert not verify_close(bet,quote,kickoff,reg)['rule_match']
