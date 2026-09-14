"""Conservative, auditable reception-zero evidence; never roster-based zeros."""
from src.ingest.ncaaf_player_stats import _number, made_attempts


def verified_reception_zeros(payload, parsed):
    """A rushing appearance plus reconciled receiving/passing totals proves zero.

    Only receptions are inferred: yards can involve laterals and longest-play
    settlement has different rules. Missing/duplicate blocks fail closed.
    """
    evidence = []
    for team in payload.get('boxscore', {}).get('players', []):
        categories = team.get('statistics', [])
        receiving = [s for s in categories if s.get('name') == 'receiving']
        passing = [s for s in categories if s.get('name') == 'passing']
        if len(receiving) != 1 or len(passing) != 1:
            continue
        rec, passing = receiving[0], passing[0]
        keys, totals = rec.get('keys', []), rec.get('totals', [])
        if keys.count('receptions') != 1 or len(keys) != len(totals):
            continue
        total = _number(totals[keys.index('receptions')])
        if total is None or total < 0 or not total.is_integer():
            continue
        catches, receivers, valid = 0, set(), True
        for row in rec.get('athletes', []):
            pid = str(row.get('athlete', {}).get('id', ''))
            values = row.get('stats', [])
            value = _number(values[keys.index('receptions')]) if len(values) == len(keys) else None
            if not pid.isdigit() or pid in receivers or row.get('didNotPlay') or value is None or value < 0 or not value.is_integer():
                valid = False
                break
            receivers.add(pid)
            catches += value
        pkeys, ptotals = passing.get('keys', []), passing.get('totals', [])
        key = 'completions/passingAttempts'
        pair = made_attempts(ptotals[pkeys.index(key)]) if pkeys.count(key) == 1 and len(pkeys) == len(ptotals) else None
        if not valid or catches != total or pair is None or pair[0] != total:
            continue
        dnp = {str(r.get('athlete', {}).get('id', '')) for s in categories for r in s.get('athletes', []) if r.get('didNotPlay')}
        rushers = {str(r.get('athlete', {}).get('id', '')) for s in categories if s.get('name') == 'rushing' for r in s.get('athletes', [])}
        for pid in sorted(rushers - receivers - dnp):
            values = parsed.get(pid, {})
            if values.get('rushing_attempts', 0) > 0 and 'receptions' not in values:
                evidence.append({'external_id': pid, 'stat': 'receptions', 'value': 0.0,
                    'rule': 'rushing_appearance_reconciled_team_receptions_v1',
                    'team_id': str(team.get('team', {}).get('id', '')),
                    'team_receptions': total, 'passing_completions': pair[0]})
    return evidence
