"""Preview/commit normalized receipt JSON; no OCR guessing or external uploads."""
import hashlib
import json
from uuid import UUID
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from src.api.routers.ledger import Entry, router, lock, terms_for, record_entry
from src.db.client import get_db
from src.models.ledger import LedgerBet, LedgerEvent


class ReceiptEntry(Entry):
    request_id: str = 'receipt_import'
    mode: Literal['actual'] = 'actual'


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    receipt_id: str = Field(min_length=1, max_length=160)
    account_alias: str = Field(min_length=1, max_length=80, description='Local nickname, not an account number')
    existing_bet_id: UUID | None = None
    entry: ReceiptEntry


class ImportBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    receipts: list[Receipt] = Field(min_length=1, max_length=100)
    preview_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def receipt_key(receipt):
    return 'receipt:' + digest([receipt.entry.book, receipt.account_alias, receipt.receipt_id])


def receipt_payload(receipt):
    entry = receipt.entry.model_dump(mode='json', exclude={'request_id'})
    return {'receipt_id': receipt.receipt_id, 'account_alias': receipt.account_alias,
            'receipt_sha256': digest(entry), 'source': 'user_imported_normalized_receipt',
            'normalized_entry': entry,
            'authentication': 'not_independently_authenticated'}


def same_placement(bet, entry, terms):
    return (bet.mode == 'actual' and bet.stake == entry.stake and bet.currency == entry.currency
        and bet.placed_at == entry.placed_at and all(bet.terms.get(k) == terms.get(k) for k in
            ('game_id','kind','player_id','market','side','line','book','price_american')))


async def inspect_batch(body, db):
    rows, prepared, keys, linked, placements = [], [], set(), set(), set()
    for index, receipt in enumerate(body.receipts):
        key = receipt_key(receipt)
        try:
            if key in keys:
                raise HTTPException(409, 'Duplicate receipt identity in this batch')
            keys.add(key)
            terms = await terms_for(db, receipt.entry)
            placement_hash = digest(receipt.entry.model_dump(mode='json', exclude={'request_id'}))
            if placement_hash in placements:
                raise HTTPException(409, 'Identical placement appears twice under different receipt IDs; reconcile before importing')
            placements.add(placement_hash)
            payload = receipt_payload(receipt)
            prior = await db.scalar(select(LedgerEvent).where(LedgerEvent.request_id == key))
            if prior:
                if prior.kind != 'receipt' or prior.payload != payload or (receipt.existing_bet_id and receipt.existing_bet_id != prior.bet_id):
                    raise HTTPException(409, 'Receipt identity already imported with different content; review the original entry')
                rows.append({'row': index+1, 'status': 'duplicate', 'bet_id': str(prior.bet_id)})
                prepared.append(None)
                continue
            bet = await db.get(LedgerBet, receipt.existing_bet_id) if receipt.existing_bet_id else None
            if receipt.existing_bet_id:
                if str(receipt.existing_bet_id) in linked:
                    raise HTTPException(409, 'Two receipts cannot attach to the same bet in one batch')
                linked.add(str(receipt.existing_bet_id))
                if not bet or not same_placement(bet, receipt.entry, terms) or any(
                    bet.terms.get(k) and terms.get(k) and bet.terms[k] != terms[k]
                    for k in ('product','jurisdiction','period')):
                    raise HTTPException(409, 'Existing bet does not exactly match receipt terms')
                other = await db.scalar(select(LedgerEvent.id).where(LedgerEvent.bet_id==bet.id, LedgerEvent.kind=='receipt').limit(1))
                if other:
                    raise HTTPException(409, 'Existing bet already has a receipt')
            else:
                # An apparently matching manual entry must be reconciled explicitly.
                candidates = (await db.scalars(select(LedgerBet).where(LedgerBet.mode=='actual',
                    LedgerBet.game_id==receipt.entry.game_id, LedgerBet.stake==receipt.entry.stake,
                    LedgerBet.currency==receipt.entry.currency, LedgerBet.placed_at==receipt.entry.placed_at))).all()
                matches = [str(b.id) for b in candidates if same_placement(b, receipt.entry, terms)]
                if matches:
                    raise HTTPException(409, {'reason':'Possible existing wager; set existing_bet_id after review', 'candidates':matches})
            rows.append({'row':index+1, 'status':'attach' if bet else 'new', 'book':receipt.entry.book,
                         'stake':str(receipt.entry.stake), 'currency':receipt.entry.currency})
            prepared.append((receipt, key, payload, bet))
        except HTTPException as exc:
            rows.append({'row':index+1, 'status':'blocked', 'reason':exc.detail})
            prepared.append(None)
    signature = digest({'receipts': body.model_dump(mode='json', exclude={'preview_sha256'}), 'rows': rows})
    return {'rows':rows, 'preview_sha256':signature, 'can_commit':all(r['status']!='blocked' for r in rows)}, prepared


@router.post('/receipts/preview')
async def preview_receipts(body: ImportBatch, db=Depends(get_db)):
    await lock(db)
    preview, _ = await inspect_batch(body, db)
    return preview


@router.post('/receipts/commit')
async def commit_receipts(body: ImportBatch, db=Depends(get_db)):
    await lock(db)
    preview, prepared = await inspect_batch(body, db)
    if all(r['status']=='duplicate' for r in preview['rows']):
        return {'imported':0, 'duplicates':len(preview['rows'])}
    if not preview['can_commit'] or body.preview_sha256 != preview['preview_sha256']:
        raise HTTPException(409, {'reason':'Preview changed or contains blocked rows; preview again', 'preview':preview})
    written = 0
    try:
        for item in prepared:
            if item is None:
                continue
            receipt, key, payload, bet = item
            if bet is None:
                req = Entry(**receipt.entry.model_dump(exclude={'request_id'}), request_id=key)
                saved = await record_entry(req, db, commit=False)
                bet_id = UUID(saved['id'])
            else:
                bet_id = bet.id
            db.add(LedgerEvent(request_id=key, bet_id=bet_id, kind='receipt', payload=payload))
            written += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {'imported':written, 'duplicates':sum(r['status']=='duplicate' for r in preview['rows']),
            'notice':'Receipt claims retained; no automatic settlement or independent authentication.'}
