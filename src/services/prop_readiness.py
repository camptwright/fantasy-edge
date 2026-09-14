"""Explain every observed NCAAF prop family without equating fitting to validation."""
import json
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_settings
from src.services.ncaaf_candidate_training import STATS
from src.services.serving_distributions import distribution_status
from src.services.stat_identity import canonical_stat


def latest_research():
    paths = sorted((Path(get_settings().raw_archive_dir)/'prop-research').glob('*.json'))
    if not paths:
        return None
    try:
        return json.loads(paths[-1].read_text())
    except (OSError, ValueError):
        return None


def readiness(quotes, facts, research):
    deployed = (distribution_status().get('evidence') or {}).get('player_props', {})
    grouped = defaultdict(list)
    for quote in quotes:
        grouped[quote['stat_type']].append(quote)
    candidates = (research or {}).get('player_props', {})
    rows = []
    for stat in sorted(set(grouped) | STATS):
        q = grouped[stat]
        qualified = sum(r.get('model_probability') is not None for r in q)
        active = sum(bool(r.get('calibration_candidate_id')) for r in q)
        candidate = candidates.get(canonical_stat(stat), {})
        if active:
            status = 'experimental_override'
            reason = 'An explicitly enabled, pinned candidate is serving; prospective validation is still required.'
            if deployed.get(stat, {}).get('user_override_approved') is True and not deployed[stat].get('deployable_experimental'):
                reason = 'Manual user override despite failed historical distribution screen; baseline retained. Not validated or demonstrated better.'
        elif canonical_stat(stat) not in STATS:
            status = 'unsupported'
            reason = ('Requires scoring rules or play-by-play/event-level outcomes and a dedicated model; '
                      'no substitute or zero result is fabricated.')
        elif candidate.get('deployable_experimental'):
            status = 'candidate_review'
            reason = 'Research candidate passed the distribution screen; not automatically deployed or validated.'
        elif candidate.get('status') == 'experimental_holdout':
            status = 'baseline_only'
            reason = 'Candidate did not improve both distribution loss and point error; baseline retained.'
        else:
            status = 'insufficient_evidence'
            reason = 'Not enough chronological training/holdout history; collection continues.'
        rows.append({'stat_type': stat, 'status': status, 'reason': reason, 'quotes': len(q),
            'canonical_stat_type': canonical_stat(stat),
            'actionable_quotes': sum(bool(r.get('actionable')) for r in q),
            'quote_blockers': dict(Counter(r.get('exclusion_reason') for r in q if r.get('exclusion_reason'))),
            'qualified_quotes': qualified, 'overridden_quotes': active,
            'historical_rows': facts.get(stat, {}).get('rows', 0),
            'historical_games': facts.get(stat, {}).get('games', 0),
            'deployment_evidence': deployed.get(stat, {}) if active else {},
            'candidate_evidence': candidate})
    return {'sport': 'ncaaf', 'as_of': datetime.now(timezone.utc).isoformat(),
        'research_at': (research or {}).get('created_at'), 'families': rows,
        'note': 'Quote counts are latest per player/stat/source/event, not independent games or recommended bets. '
                'Composite history requires every component and can be selection-biased. '
                'Research never automatically replaces pinned serving parameters.'}
