"""Exact-contract sharp-reference comparisons, not approved betting advice.

No interpolation across handicaps and no pooled prices from the target book.
Book brands, not provider feeds, are the reference sampling unit.
"""
from collections import defaultdict
from datetime import timedelta
import math

from src.utils.odds_math import remove_vig_two_way, expected_value_percent

SHARP = {'pinnacle', 'circa', 'betonlineag'}
TARGETS = {'draftkings', 'fanduel', 'betmgm', 'caesars', 'espnbet'}


def brand(source):
    for prefix in ('theodds_', 'parlay_', 'sgo_'):
        if source.startswith(prefix):
            return source[len(prefix):]
    return source


def comparisons(rows):
    """Input is latest, availability-confirmed pregame (line, game) pairs."""
    groups = defaultdict(dict)
    for line, game in rows:
        if brand(line.source) not in SHARP | TARGETS:
            continue
        groups[(line.game_id, line.market, line.source)][line.side] = (line, game)
    references = defaultdict(dict)
    targets = []
    for (game_id, market, source), sides in groups.items():
        names = ('over', 'under') if market == 'total' else ('home', 'away')
        if market not in ('moneyline', 'spread', 'total') or any(s not in sides for s in names):
            continue
        first, game = sides[names[0]]
        second, _ = sides[names[1]]
        prices = (first.price_american, second.price_american)
        if any(not isinstance(p, int) or isinstance(p, bool) or abs(p) < 100 for p in prices):
            continue
        if abs(first.observed_at-second.observed_at) > timedelta(seconds=60):
            continue
        if market != 'moneyline':
            if any(x.line is None or not math.isfinite(x.line) for x in (first, second)):
                continue
            if (first.line != second.line if market == 'total' else first.line != -second.line):
                continue
            # Two-way devig cannot identify an unconditional push probability.
            if float(first.line).is_integer():
                continue
        fair = remove_vig_two_way(*prices)
        for line, probability in zip((first, second), fair):
            key = (game_id, market, line.side, line.line)
            if brand(source) in SHARP:
                previous = references[key].get(brand(source))
                entry = (line, probability)
                if previous is None or (line.observed_at, str(line.id)) > (previous[0].observed_at, str(previous[0].id)):
                    references[key][brand(source)] = entry
            else:
                targets.append((key, line, game))
    out = []
    for key, target, game in targets:
        refs = references.get(key, {})
        # Quotes must also be contemporaneous across reference and target.
        refs = {b: v for b, v in refs.items()
                if abs(v[0].observed_at-target.observed_at) <= timedelta(minutes=5)}
        if not refs:
            continue
        probability = sum(v[1] for v in refs.values()) / len(refs)
        out.append({'id': str(target.id), 'game_id': str(game.id), 'sport': game.sport,
            'market': target.market, 'side': target.side, 'line': target.line,
            'bookmaker': brand(target.source), 'source': target.source,
            'price_american': target.price_american, 'fair_probability': probability,
            'ev_percent': expected_value_percent(probability, target.price_american),
            'reference_books': sorted(refs),
            'reference_quote_ids': [str(refs[b][0].id) for b in sorted(refs)],
            'reference_observed_at': [refs[b][0].observed_at.isoformat() for b in sorted(refs)],
            'observed_at': target.observed_at.isoformat(),
            'pricing_method': 'sharp_exact_contract_equal_brand_v1',
            'actionable': False, 'usage': 'research_only',
            'exclusion_reason': 'missing_prospective_strategy_validation'})
    return sorted(out, key=lambda row: (-row['ev_percent'], row['id']))
