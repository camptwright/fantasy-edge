"""Cross-feed final totals audit. Never infer identity from display names."""
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from src.ingest.nfl_results import parse_boxscore
from src.services.period_history import number

FIELDS = {'passing_yards': 'passing_yards', 'receiving_yards': 'receiving_yards',
          'rushing_yards': 'rushing_yards', 'receptions': 'receptions', 'carries': 'rushing_attempts'}


def crosswalk(rows):
    """Duplicate identical mappings are harmless; either-side conflicts are not."""
    forward, reverse = defaultdict(set), defaultdict(set)
    for row in rows:
        gsis, espn = row.get('gsis_id'), row.get('espn_id')
        if gsis and espn and str(espn).isdigit():
            forward[str(gsis)].add(str(espn))
            reverse[str(espn)].add(str(gsis))
    return {gsis: next(iter(ids)) for gsis, ids in forward.items()
            if len(ids) == 1 and len(reverse[next(iter(ids))]) == 1}


def compare(summary, schedule, nfl_box, identities):
    event = str(schedule.get('espn') or '')
    blockers, comparisons = [], []
    try:
        competition = next(c for c in summary['header']['competitions'] if str(c['id']) == event)
        date = datetime.fromisoformat(competition['date'].replace('Z', '+00:00'))
        if date.tzinfo is None or date.astimezone(ZoneInfo('America/New_York')).date().isoformat() != schedule['gameday']:
            blockers.append('event_date_mismatch')
        sides = {r['homeAway']: r for r in competition['competitors']}
        if any(float(sides[side]['score']) != schedule[side+'_score'] for side in ('home', 'away')):
            blockers.append('independent_final_score_mismatch')
        espn_box = parse_boxscore(summary, event)
    except (KeyError, ValueError, TypeError, StopIteration):
        return {'game_id': schedule['game_id'], 'blockers': ['invalid_independent_final'], 'comparisons': [], 'ready': False}
    mapped, missing = {}, []
    for row in nfl_box:
        player = row.get('player_id')
        if not player or player not in identities:
            missing.append(player)
            continue
        external = identities[player]
        if external in mapped:
            blockers.append('duplicate_player_row')
        mapped[external] = row
    for external in sorted(set(mapped) | set(espn_box)):
        row = mapped.get(external, {})
        stats = espn_box.get(external, {})
        for source_stat, canonical in FIELDS.items():
            left, right = row.get(source_stat), stats.get(canonical)
            if left is None and right is None:
                continue
            # Zero in nflverse is not proof of an omitted ESPN category.
            state = ('missing_nflverse' if not number(left) else 'missing_espn' if not number(right)
                     else 'matched' if left == right else 'mismatch')
            comparisons.append({'espn_id': external, 'stat': canonical, 'nflverse': left,
                                'espn': right, 'state': state})
    if missing:
        blockers.append('unmapped_player_rows')
    counts = dict(Counter(r['state'] for r in comparisons))
    return {'game_id': schedule['game_id'], 'espn_event_id': event,
        'blockers': sorted(set(blockers)), 'unmapped_player_rows': len(missing),
        'comparisons': comparisons, 'counts': counts,
        'ready': bool(comparisons) and not blockers and all(r['state'] == 'matched' for r in comparisons),
        'serving_enabled': False, 'note': 'Independent feed corroboration does not prove period allocation.'}
