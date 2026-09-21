"""Tracking only: no bookmaker transactions, Kelly changes or model promotions."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from src.models.base import utcnow
from src.models.facts import Game, PlayerPropLine, TeamMarketLine
from src.models.ledger import LedgerBet, LedgerEvent, LedgerPolicy


def exposure(bets, settlements, currency, mode='actual'):
    totals = {k: defaultdict(Decimal) for k in ('sport', 'game', 'player', 'book')}
    gross = Decimal('0')
    for b in bets:
        if b.currency != currency or b.mode != mode or settlements.get(str(b.id), {}).get('status', 'open') != 'open':
            continue
        gross += b.stake
        for key, value in [('sport', b.terms['sport']), ('game', str(b.game_id)), ('player', b.terms.get('player_id')), ('book', b.terms['book'])]:
            if value:
                totals[key][value] += b.stake
    return {'gross': str(gross), **{k: {v: str(n) for v, n in rows.items()} for k, rows in totals.items()}}


def check_limits(current, terms, stake, limits):
    """Gross stakes, no assumed netting or independence between related bets."""
    failures = []
    checks = {'total': Decimal(current['gross']) + stake, 'single': stake}
    for axis in ('sport', 'game', 'player', 'book'):
        value = terms.get(axis if axis in ('sport', 'book') else axis + '_id')
        if value:
            checks[axis] = Decimal(current[axis].get(value, '0')) + stake
    for axis, value in checks.items():
        if limits.get(axis) is not None and value > Decimal(limits[axis]):
            failures.append({'axis': axis, 'projected': str(value), 'limit': limits[axis]})
    return {'status': 'unconfigured' if not limits else ('blocked' if failures else 'within_configured_limits'), 'breaches': failures}


async def state(db):
    bets = list((await db.scalars(select(LedgerBet).order_by(LedgerBet.created_at.desc()))).all())
    events = list((await db.scalars(select(LedgerEvent).order_by(LedgerEvent.created_at, LedgerEvent.id))).all())
    settlements, closes = {}, {}
    for e in events:
        if e.kind in ('settlement', 'close'):
            (settlements if e.kind == 'settlement' else closes)[str(e.bet_id)] = e.payload
    policies = {}
    for p in (await db.scalars(select(LedgerPolicy).order_by(LedgerPolicy.created_at, LedgerPolicy.id))).all():
        policies[p.currency] = p.limits
    return bets, events, settlements, closes, policies


async def capture_closes(db):
    """Snapshot observed pre-start prices, not a claim of official bookmaker close.

    Quote tables lack settlement-rule identity: even an exact-line match remains
    a proxy. No CLV percentage or automatic profitability claim is emitted.
    """
    bets, _, _, closes, _ = await state(db)
    written = 0
    now = utcnow()
    from src.services.ledger_rules import verify_close, load_registry
    registry = load_registry()
    for bet in bets:
        game = await db.get(Game, bet.game_id)
        if not game or not game.game_time or game.game_time > now:
            if str(bet.id) in closes:
                pending = {'status':'kickoff_unconfirmed_or_rescheduled', 'clv_percent':None}
                if closes[str(bet.id)] != pending:
                    db.add(LedgerEvent(request_id=uuid4().hex, bet_id=bet.id, kind='close', payload=pending))
                    written += 1
            continue
        terms = bet.terms
        model = PlayerPropLine if terms['kind'] == 'player' else TeamMarketLine
        filters = [model.game_id == bet.game_id, model.source == terms['book'],
                   model.observed_at < game.game_time, model.observed_at >= bet.placed_at,
                   model.observed_at >= game.game_time - timedelta(minutes=30)]
        if terms['kind'] == 'player':
            filters += [model.player_id == terms['player_id'], model.stat_type == terms['market'], model.line == terms['line']]
        else:
            filters += [model.market == terms['market'], model.side == terms['side'], model.line == terms['line']]
        quote = await db.scalar(select(model).where(*filters).order_by(model.observed_at.desc(), model.id.desc()).limit(1))
        price = None if quote is None else (getattr(quote, terms['side'] + '_price_american') if terms['kind'] == 'player' else quote.price_american)
        payload = {'status': 'missing_comparable_pregame_quote', 'kickoff': game.game_time.isoformat(), 'clv_percent': None}
        if price is not None and abs(price) >= 100:
            payload.update(status='observed_price_proxy_rules_unverified', quote_id=str(quote.id), observed_at=quote.observed_at.isoformat(), price_american=price)
            verification = verify_close(bet, quote, game.game_time, registry)
            payload['verification'] = verification
            if verification['official_close']:
                payload.update(status='verified_same_line_clv', clv_percent=verification['clv_percent'])
            elif verification['rule_match']:
                payload['status'] = 'rules_matched_observed_close_proxy'
        if closes.get(str(bet.id)) != payload:
            db.add(LedgerEvent(request_id=uuid4().hex, bet_id=bet.id, kind='close', payload=payload))
            written += 1
    await db.commit()
    return {'captured': written, 'scope': 'stored exact-line pregame observations; settlement rules unverified'}
