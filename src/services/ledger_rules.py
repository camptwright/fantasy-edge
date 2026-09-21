"""Fail-closed, reviewed evidence registry. Client assertions cannot verify CLV.

Rules and quote/receipt mappings enter this operator-reviewed configuration only
after source inspection. No HTTP import accepts a `verified` switch or fetches
arbitrary URLs. The empty registry is deliberate until real evidence is available.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from src.services.settlement_binding import bind
from src.utils.odds_math import american_to_decimal

REGISTRY = Path(__file__).resolve().parents[2] / 'config' / 'ledger_closing_evidence.json'


def load_registry():
    try:
        value = json.loads(REGISTRY.read_text())
        if value.get('schema_version') != 1 or any(not isinstance(value.get(k), dict) for k in ('rules','quotes','receipts')):
            return {}
        return value
    except (ValueError, OSError, AttributeError):
        return {}


def registry_status():
    registry = load_registry()
    return {'rule_contracts': len(registry.get('rules', {})),
            'reviewed_quote_mappings': len(registry.get('quotes', {})),
            'reviewed_receipt_mappings': len(registry.get('receipts', {})),
            'requirements': ['Archived complete official rules with effective interval',
                'Exact receipt and quote book/product/jurisdiction/period mapping',
                'Independently evidenced official closing designation, not just last observation'],
            'status': 'evidence_registry_available' if registry.get('quotes') else 'awaiting_source_evidence'}


def _reviewed(item):
    if not isinstance(item, dict):
        return False
    source = item.get('source_snapshot')
    return (isinstance(source, str) and bool(source.strip()) and bool(item.get('source_url'))
        and bool(item.get('reviewed_by')) and bool(item.get('reviewed_at'))
        and hashlib.sha256(source.encode()).hexdigest() == item.get('source_sha256'))


def verify_close(bet, quote, kickoff, registry=None):
    registry = load_registry() if registry is None else registry
    terms = bet.terms
    result = {'rule_match': False, 'official_close': False, 'clv_percent': None, 'blockers': []}
    quote_evidence = registry.get('quotes', {}).get(str(quote.id), {})
    receipt_evidence = registry.get('receipts', {}).get(str(bet.id), {})
    if not _reviewed(quote_evidence) or not _reviewed(receipt_evidence):
        result['blockers'] = ['missing_reviewed_quote_or_receipt_identity']
        return result
    # Evidence ties the exact economic contract to both IDs, not merely the book.
    expected = {k: terms.get(k) for k in ('game_id','kind','player_id','market','side','line','book','product','jurisdiction','period')}
    for evidence in (quote_evidence, receipt_evidence):
        if evidence.get('contract') != expected or not terms.get('product') or not terms.get('jurisdiction'):
            result['blockers'].append('contract_identity_mismatch')
    closing_price = getattr(quote, terms['side'] + '_price_american') if terms['kind'] == 'player' else quote.price_american
    if (quote_evidence.get('price_american') != closing_price
        or receipt_evidence.get('price_american') != terms['price_american']
        or quote_evidence.get('observed_at') != quote.observed_at.isoformat()
        or receipt_evidence.get('placed_at') != bet.placed_at.isoformat()):
        result['blockers'].append('price_or_timestamp_evidence_mismatch')
    rule_ids = [receipt_evidence.get('rule_id'), quote_evidence.get('rule_id')]
    if not rule_ids[0] or rule_ids[0] != rule_ids[1]:
        result['blockers'].append('different_rule_versions')
    rule = registry.get('rules', {}).get(rule_ids[0], {})
    if not isinstance(rule, dict):
        rule = {}
    snapshot = rule.get('source_snapshot', '')
    snapshot = snapshot.encode() if isinstance(snapshot, str) else b''
    if not _reviewed(rule) or rule.get('source') != rule.get('source_url'):
        result['blockers'].append('rule_not_reviewed')
    for identifier, at in ((str(bet.id), bet.placed_at), (str(quote.id), quote.observed_at)):
        contract = {k: terms.get(k) for k in ('book','product','jurisdiction','market')}
        contract.update(sport=terms.get('sport'), quote_id=identifier, captured_at=at.isoformat())
        binding = bind(contract, rule, source_snapshot=snapshot)
        result['blockers'].extend(binding['blockers'])
    result['blockers'] = sorted(set(result['blockers']))
    result['rule_match'] = not result['blockers']
    if result['rule_match']:
        result['rule_id'] = rule_ids[0]
        result['rule_source_sha256'] = rule.get('source_sha256')
        result['quote_evidence_sha256'] = quote_evidence.get('source_sha256')
        if quote_evidence.get('designation') != 'official_pregame_close' or quote_evidence.get('kickoff') != kickoff.isoformat():
            result['blockers'].append('official_close_not_evidenced')
        elif not bet.placed_at <= quote.observed_at < kickoff:
            result['blockers'].append('invalid_close_timing')
        else:
            price = getattr(quote, terms['side'] + '_price_american') if terms['kind'] == 'player' else quote.price_american
            if price is None or abs(price) < 100:
                result['blockers'].append('invalid_close_price')
            else:
                result['official_close'] = True
                # Exact same-line gross return ratio; explicitly NOT no-vig EV.
                result['clv_percent'] = round(100 * (american_to_decimal(terms['price_american']) / american_to_decimal(price) - 1), 4)
                result['metric'] = 'same_line_decimal_price_improvement_percent_not_no_vig_ev'
    return result
