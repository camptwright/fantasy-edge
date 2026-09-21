from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, AwareDatetime, model_validator, ConfigDict
from sqlalchemy import select, text
from src.db.client import get_db
from src.models.base import utcnow
from src.models.facts import Game
from src.models.identity import Player
from src.models.ledger import LedgerBet, LedgerEvent, LedgerPolicy
from src.services.betting_ledger import state, exposure, check_limits, capture_closes

router = APIRouter(prefix='/api/v1/ledger', tags=['ledger'])
Money = Annotated[Decimal, Field(ge=0, le=999999999999, max_digits=14, decimal_places=2)]


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=8, max_length=80)
    mode: Literal['paper', 'actual']
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    stake: Money
    placed_at: AwareDatetime
    game_id: UUID
    kind: Literal['team', 'player']
    player_id: UUID | None = None
    market: str = Field(min_length=1, max_length=48)
    side: Literal['home', 'away', 'over', 'under']
    line: Decimal | None = Field(default=None, allow_inf_nan=False, ge=-1000000, le=1000000, decimal_places=4)
    price_american: int = Field(ge=-100000, le=100000)
    book: str = Field(min_length=1, max_length=32, pattern=r'^\S+$')
    settlement_rules: str = Field(min_length=1, max_length=2000)
    quote_id: UUID | None = None
    product: str | None = Field(default=None, min_length=1, max_length=80)
    jurisdiction: str | None = Field(default=None, min_length=1, max_length=40)
    period: str = Field(default='full_game', min_length=1, max_length=40)

    @model_validator(mode='after')
    def valid(self):
        if self.stake <= 0 or abs(self.price_american) < 100:
            raise ValueError('Positive stake and valid American odds required')
        if self.kind == 'team':
            if self.player_id or self.market not in ('moneyline', 'spread', 'total'):
                raise ValueError('Team singles only: moneyline, spread, total')
            if self.side not in (('over', 'under') if self.market == 'total' else ('home', 'away')):
                raise ValueError('Side does not match market')
        elif self.player_id is None or self.side not in ('over', 'under'):
            raise ValueError('Player singles require exact player and over/under side')
        if (self.market == 'moneyline') != (self.line is None):
            raise ValueError('Only moneyline has no line')
        if self.placed_at > utcnow():
            raise ValueError('Placement time cannot be in the future')
        return self


async def lock(db):
    # Serialize ledger writes and preflight snapshots, including duplicate requests.
    await db.execute(text('SELECT pg_advisory_xact_lock(78241903)'))


async def terms_for(db, entry):
    game = await db.get(Game, entry.game_id)
    if game is None:
        raise HTTPException(422, 'Unknown game')
    if entry.player_id:
        player = await db.get(Player, entry.player_id)
        if not player or player.sport != game.sport:
            raise HTTPException(422, 'Player must exist in the same sport as the game')
    terms = entry.model_dump(mode='json', exclude={'request_id', 'mode', 'currency', 'stake', 'placed_at'})
    terms['sport'] = game.sport
    terms['line'] = float(entry.line) if entry.line is not None else None
    if entry.quote_id:
        from src.services.ledger_quotes import resolve_quote
        quoted = await resolve_quote(db, entry.kind, entry.quote_id, entry.side)
        if any(terms.get(k) != quoted['terms'].get(k) for k in
               ('game_id', 'kind', 'player_id', 'market', 'side', 'line', 'book')):
            raise HTTPException(422, 'Receipt contract differs from linked quote; use manual entry instead')
        # Actual receipt price can differ from the earlier displayed offer.
        terms['offered_price_american'] = quoted['terms']['price_american']
        terms['quote_observed_at'] = quoted['observed_at']
    return terms


@router.get('')
async def summary(db=Depends(get_db)):
    bets, events, settlements, closes, policies = await state(db)
    currencies = sorted({b.currency for b in bets} | set(policies))
    return {'scope': 'manual/paper singles; no bet execution', 'policies': policies,
            'exposure': {c: {m: exposure(bets, settlements, c, m) for m in ('actual', 'paper')} for c in currencies},
            'items': [{'id': str(b.id), 'mode': b.mode, 'currency': b.currency, 'stake': str(b.stake), 'placed_at': b.placed_at,
                       'terms': b.terms, 'settlement': settlements.get(str(b.id), {'status': 'open'}),
                       'closing': closes.get(str(b.id), {'status': 'awaiting_capture'})} for b in bets],
            'event_count': len(events)}


@router.post('/preflight')
async def preflight(entry: Entry, db=Depends(get_db)):
    await lock(db)
    terms = await terms_for(db, entry)
    bets, _, settlements, _, policies = await state(db)
    return check_limits(exposure(bets, settlements, entry.currency, entry.mode), terms, entry.stake, policies.get(entry.currency, {}))


@router.post('/bets')
async def record(entry: Entry, db=Depends(get_db)):
    return await record_entry(entry, db)


async def record_entry(entry: Entry, db, *, commit=True):
    await lock(db)
    terms = await terms_for(db, entry)
    old = await db.scalar(select(LedgerBet).where(LedgerBet.request_id == entry.request_id))
    if old:
        if old.terms != terms or old.stake != entry.stake or old.mode != entry.mode or old.currency != entry.currency or old.placed_at != entry.placed_at:
            raise HTTPException(409, 'Idempotency key already used with different placement terms')
        return {'id': str(old.id), 'created': False}
    if entry.mode == 'paper' and entry.quote_id:
        from src.services.ledger_quotes import resolve_quote
        offered = await resolve_quote(db, entry.kind, entry.quote_id, entry.side)
        if offered['availability'] != 'current_pregame_offer' or offered['terms']['price_american'] != entry.price_american:
            raise HTTPException(409, 'Paper quote is stale, withdrawn, started, or its price changed. Refresh Best Bets.')
    bets, _, settlements, _, policies = await state(db)
    risk = check_limits(exposure(bets, settlements, entry.currency, entry.mode), terms, entry.stake, policies.get(entry.currency, {}))
    # Actual history must be recorded honestly even if it exceeds a saved limit.
    if entry.mode == 'paper' and risk['status'] == 'blocked':
        raise HTTPException(409, risk)
    bet = LedgerBet(request_id=entry.request_id, mode=entry.mode, currency=entry.currency, stake=entry.stake,
                    placed_at=entry.placed_at, game_id=entry.game_id, terms=terms)
    db.add(bet)
    await db.flush()
    if commit:
        await db.commit()
    return {'id': str(bet.id), 'created': True, 'risk': risk}


class Settlement(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    status: Literal['open', 'won', 'lost', 'push', 'void', 'cashout']
    returned: Money
    evidence: str = Field(min_length=1, max_length=2000)


@router.post('/bets/{bet_id}/settlements')
async def settle(bet_id: UUID, change: Settlement, db=Depends(get_db)):
    await lock(db)
    bet = await db.get(LedgerBet, bet_id)
    if not bet:
        raise HTTPException(404, 'Unknown ledger bet')
    if ((change.status in ('open', 'lost') and change.returned != 0)
        or (change.status in ('push', 'void') and change.returned != bet.stake)
        or (change.status == 'won' and change.returned <= bet.stake)):
        raise HTTPException(422, 'Returned amount must include stake and agree with settlement status')
    payload = change.model_dump(mode='json', exclude={'request_id'})
    payload['profit'] = None if change.status == 'open' else str(change.returned - bet.stake)
    old = await db.scalar(select(LedgerEvent).where(LedgerEvent.request_id == change.request_id))
    if old:
        if old.bet_id != bet_id or old.kind != 'settlement' or old.payload != payload:
            raise HTTPException(409, 'Idempotency key already used')
        return {'created': False}
    db.add(LedgerEvent(request_id=change.request_id, bet_id=bet_id, kind='settlement', payload=payload))
    await db.commit()
    return {'created': True}


class Policy(BaseModel):
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    single: Money | None = None
    total: Money | None = None
    sport: Money | None = None
    game: Money | None = None
    player: Money | None = None
    book: Money | None = None


@router.post('/policy')
async def policy(body: Policy, db=Depends(get_db)):
    await lock(db)
    limits = body.model_dump(mode='json', exclude={'currency'}, exclude_none=True)
    db.add(LedgerPolicy(currency=body.currency, limits=limits))
    await db.commit()
    return {'currency': body.currency, 'limits': limits, 'status': 'configured' if limits else 'unconfigured'}


@router.get('/bets/{bet_id}/events')
async def audit(bet_id: UUID, db=Depends(get_db)):
    return [{'id': str(e.id), 'kind': e.kind, 'at': e.created_at, 'payload': e.payload} for e in
            (await db.scalars(select(LedgerEvent).where(LedgerEvent.bet_id == bet_id).order_by(LedgerEvent.created_at, LedgerEvent.id))).all()]


@router.post('/capture-closes')
async def capture(db=Depends(get_db)):
    await lock(db)
    return await capture_closes(db)


@router.get('/quote/{kind}/{quote_id}')
async def quote_draft(kind: Literal['team', 'player'], quote_id: UUID,
                      side: Literal['home', 'away', 'over', 'under'], db=Depends(get_db)):
    from src.services.ledger_quotes import resolve_quote
    return await resolve_quote(db, kind, quote_id, side)


@router.get('/closing-evidence-status')
async def evidence_status():
    from src.services.ledger_rules import registry_status
    return registry_status()
