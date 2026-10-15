"""Personal dynasty package scenarios; market indices are separate from points."""
from math import isfinite


def number(value):
    try:
        return type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def plan(data, side_a, side_b, *, goal="balanced", picks=(), market=None, lineup=None):
    if goal not in {"balanced", "contender", "rebuild"}:
        return {"status": "invalid_goal"}
    a, b = list(map(str, side_a)), list(map(str, side_b))
    if not a and not b and not picks:
        return {"status": "empty_package"}
    if len(a + b) > 12 or len(set(a + b)) != len(a + b):
        return {"status": "invalid_player_selection"}
    known = {str(p['player_id']) for p in data.get('players', [])}
    if any(p not in known for p in a + b):
        return {"status": "unknown_player"}
    if len(picks) > 12:
        return {"status": "invalid_picks"}
    clean, seen = [], set()
    for p in picks:
        if not isinstance(p, dict):
            return {"status": "invalid_picks"}
        side, season, rnd, slot = (p.get(k) for k in ('side', 'season', 'round', 'slot'))
        if side not in ('a', 'b') or type(season) is not int or not 2020 <= season <= 2100 or type(rnd) is not int or not 1 <= rnd <= 10:
            return {"status": "invalid_picks"}
        if slot is not None and (type(slot) is not int or not 1 <= slot <= 32):
            return {"status": "invalid_picks"}
        identity = (season, rnd, slot, p.get('original_roster_id'))
        if identity in seen:
            return {"status": "duplicate_pick"}
        seen.add(identity)
        value = p.get('value')
        if value is not None and (not number(value) or not isinstance(p.get('source'), str) or not p['source'].strip()):
            return {"status": "invalid_pick_value"}
        clean.append({**p, 'value': value, 'valuation_type': 'user_supplied_market_index_scenario' if value is not None else 'unpriced'})
    market = market or {}
    values = {str(p['player_id']): p.get('value') for p in market.get('players', []) if p.get('identity_status') == 'exact'}
    packages = {}
    for side, ids in (('a', a), ('b', b)):
        owned_picks = [p for p in clean if p['side'] == side]
        missing = [p for p in ids if not number(values.get(p))]
        unpriced = [p for p in owned_picks if p['value'] is None]
        observed = sum(values[p] for p in ids if number(values.get(p)))
        packages[side] = {'player_ids': ids, 'picks': owned_picks,
                          'observed_player_index': observed if not missing else None,
                          'scenario_package_index': observed + sum(p['value'] or 0 for p in owned_picks) if not missing and not unpriced and market.get('status') == 'observed' else None,
                          'unpriced_player_ids': missing, 'unpriced_picks': len(unpriced)}
    va, vb = (packages[s]['scenario_package_index'] for s in ('a', 'b'))
    return {'status': 'scenario', 'goal': goal, 'packages': packages,
            'side_a_market_index_change': vb - va if va is not None and vb is not None else None,
            'lineup_outlook': lineup, 'market_captured_at': market.get('captured_at'),
            'goal_guidance': {'contender': 'Compare current lineup gains and depth before market-index balance.',
                              'rebuild': 'Compare young-player and rookie-pick assets; current lineup losses may be intentional.',
                              'balanced': 'Review both current lineup impact and long-term market-index balance.'}[goal],
            'pick_ownership_verified': False,
            'note': 'Pick prices are your supplied scenarios in the same market-index units. Future pick prices and ownership are not inferred; index values are not fantasy points.'}
