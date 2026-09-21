"""Snapshot exact quote-contract identity. Partial rules can never authorize grading."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime


def bind(quote, rule=None, *, source_snapshot=None):
    required = ('book', 'product', 'jurisdiction', 'sport', 'market', 'quote_id', 'captured_at')
    missing = [key for key in required if not quote.get(key)]
    blockers = ['missing_' + k for k in missing]
    if rule is None:
        blockers.append('no_verified_rule_contract')
    else:
        if any(quote.get(k) != rule.get(k) for k in ('book', 'product', 'jurisdiction', 'sport', 'market')):
            blockers.append('contract_identity_mismatch')
        if rule.get('status') != 'verified' or rule.get('unresolved'):
            blockers.append('incomplete_rule_contract')
        digest = rule.get('source_sha256')
        if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or not rule.get('source') or not isinstance(source_snapshot, bytes)
                or not source_snapshot or hashlib.sha256(source_snapshot).hexdigest() != digest):
            blockers.append('missing_rule_source_snapshot')
        clauses = rule.get('clauses') or {}
        needed = ['stat_definition', 'participation', 'overtime', 'void_conditions', 'push_treatment']
        if re.match(r'^[1-4][qh]_',quote.get('market') or ''):
            needed += ['period_definition','period_completion']
        if 'td_scorer' in (quote.get('market') or ''):
            needed += ['no_touchdown', 'unlisted_scorer', 'selection_universe']
        if not isinstance(clauses, dict) or any(not clauses.get(k) for k in needed):
            blockers.append('missing_settlement_clauses')
        try:
            captured = datetime.fromisoformat(quote['captured_at'])
            observed = datetime.fromisoformat(rule['source_observed_at'])
            if observed.tzinfo is None or observed>captured:
                blockers.append('rule_source_not_available_at_capture')
            start, end = (datetime.fromisoformat(rule[k]) for k in ('effective_from', 'effective_until'))
            if any(t.tzinfo is None for t in (captured, start, end)) or not start <= captured < end:
                blockers.append('rule_outside_effective_interval')
        except (KeyError, TypeError, ValueError):
            blockers.append('invalid_rule_effective_interval')
    snapshot = {'quote_contract': {k: quote.get(k) for k in required}, 'rule_contract': deepcopy(rule),
                'blockers': sorted(set(blockers)), 'ready': not blockers}
    snapshot['binding_sha256'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return snapshot
