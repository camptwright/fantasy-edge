"""Prospective, one-dollar paper observations of qualified advice only."""
import hashlib
import json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from src.models.base import utcnow
from src.models.ledger import LedgerBet


async def capture(db):
    from src.api.routers.sportsbook import signal_rows, prop_rows
    from src.api.routers.ledger import Entry, lock, record_entry
    from src.services.ledger_quotes import resolve_quote
    # Compute through the same identity/approval gates as the user-facing feeds.
    rows = [('team', r) for r in await signal_rows(db, None)]
    rows += [('player', r) for r in await prop_rows(db, None, live_only=True)]
    report = dict(examined=len(rows), qualified=0, captured=0, duplicates=0, rejected=0)
    await lock(db)
    for kind, row in rows:
        if row.get('actionable') is not True or not row.get('model_version'):
            continue
        sides = [row['side']] if kind == 'team' else [s for s in ('over', 'under')
            if (row.get('edge_percent' if s == 'over' else 'under_edge_percent') or 0) > 0]
        for side in sides:
            report['qualified'] += 1
            try:
                draft = await resolve_quote(db, kind, UUID(row['id']), side)
                terms = draft['terms']
                # First capture per economic contract/model, not every polling tick
                # or price movement. Quote and placement times remain immutable.
                identity = {k: v for k, v in terms.items() if k not in ('quote_id', 'price_american')}
                identity['model_version'] = row['model_version']
                identity['cohort_version'] = row.get('cohort_version')
                key = 'auto-paper:' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                if await db.scalar(select(LedgerBet.id).where(LedgerBet.request_id == key)):
                    report['duplicates'] += 1
                    continue
                entry = Entry(**terms, request_id=key, mode='paper', currency='USD', stake='1.00',
                    placed_at=utcnow(), settlement_rules='Unverified provider contract; paper observation only')
                result = await record_entry(entry, db, commit=False)
                bet = await db.get(LedgerBet, UUID(result['id']))
                bet.terms = {**bet.terms, 'origin': 'automatic_qualified_signal_v1',
                    'prediction_evidence': row, 'unit_policy': 'fixed_one_USD_paper_not_recommended_stake'}
                report['captured'] += 1
            except HTTPException as exc:
                if exc.status_code not in (404, 409, 422):
                    raise
                report['rejected'] += 1
    await db.commit()
    return report
