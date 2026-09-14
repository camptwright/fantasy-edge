"""Explicit semantic aliases; never fuzzy-match statistical definitions."""
import math
ALIASES = {'ints_thrown': 'passing_interceptions'}


def canonical_stat(stat):
    return ALIASES.get(stat, stat)


def canonical_results(rows):
    """One outcome per player/event/stat, canonical source name preferred."""
    out = {}
    for row in sorted(rows, key=lambda r: r.stat_type in ALIASES, reverse=True):
        if not math.isfinite(row.value):
            continue
        out[(row.player_id, row.game_id, canonical_stat(row.stat_type))] = row.value
    return out
