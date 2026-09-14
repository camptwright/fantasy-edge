"""Frozen prospective research: leave-target-book-out market information.

Never imported by serving calculations. No model fitting or automatic promotion.
Only compare identical player/event/stat/line, with two other bookmaker brands.
Bookmaker brands are distinct observations, not statistically independent sources.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import statistics

from src.services.stat_identity import canonical_stat
from src.utils.odds_math import remove_vig_two_way

BOOKS = {'theodds_fanduel': 'fanduel', 'sgo_bovada': 'bovada', 'sgo_espnbet': 'espnbet',
         'parlay_draftkings': 'draftkings', 'parlay_pinnacle': 'pinnacle',
         'parlay_caesars': 'caesars', 'parlay_betmgm': 'betmgm'}


def probability(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def forecasts(props, as_of):
    groups = defaultdict(dict)
    targets = {}
    for row in props:
        book = BOOKS.get(row.get('source'))
        try:
            seen = datetime.fromisoformat(row['last_seen_at'])
            kickoff = datetime.fromisoformat(row['game_time'])
            if (not row.get('actionable') or not book or not row.get('player_id') or not row.get('game_id')
                    or not 0 <= (as_of-seen).total_seconds() <= 900 or kickoff <= as_of):
                continue
            over, under = row['over_price_american'], row['under_price_american']
            if any(not isinstance(p, int) or isinstance(p, bool) or abs(p) < 100 for p in (over, under)):
                continue
            line = float(row['line'])
            if not math.isfinite(line):
                continue
            key = (row['sport'], row['game_id'], row['player_id'], canonical_stat(row['stat_type']), line)
            fair, _ = remove_vig_two_way(over, under)
            # One quote per book. Conflicting duplicate rows invalidate this book.
            if book in groups[key]:
                groups[key][book] = None
            else:
                groups[key][book] = (fair, row['id'])
            targets[row['id']] = (key, book, row.get('baseline_model_probability'))
        except (KeyError, ValueError, TypeError):
            continue
    version = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    out = {}
    for quote_id, (key, target_book, baseline) in targets.items():
        others = {b: value for b, value in groups[key].items() if b != target_book and value is not None}
        if len(others) < 2 or not probability(baseline):
            continue
        consensus = statistics.median(value[0] for value in others.values())
        evidence = {'recipe_version': version, 'market_weight': .25,
            'market_probability': consensus, 'reference_books': sorted(others),
            'reference_quote_ids': [others[b][1] for b in sorted(others)],
            'target_book_excluded': target_book, 'as_of': as_of.astimezone(timezone.utc).isoformat(),
            'serving_enabled': False}
        out[quote_id] = {
            'market_consensus_only_v1': {**evidence, 'market_weight': 1.0, 'model_probability': consensus},
            'market_blend_25_v1': {**evidence, 'model_probability': .75*baseline+.25*consensus},
        }
    return out
