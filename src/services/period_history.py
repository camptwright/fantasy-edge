"""NFL period research labels. Reconciliation is not independent-source validation."""
from collections import defaultdict
import math

FIELDS = {'passing_yards': ('passer_player_id', 'passing_yards'),
          'receiving_yards': ('receiver_player_id', 'receiving_yards'),
          'rushing_yards': ('rusher_player_id', 'rushing_yards'),
          'receptions': ('receiver_player_id', 'complete_pass'),
          'carries': ('rusher_player_id', 'rush_attempt')}


def number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and float(value).is_integer())


def validate_game(plays, box, schedule):
    reasons, family_reasons = set(), defaultdict(set)
    totals, quarters = defaultdict(int), defaultdict(lambda: defaultdict(int))
    labels, touchdowns = [], []
    rows = [r for r in plays if r.get('play_deleted') == 0]
    if not rows or not all(number(r.get('order_sequence')) for r in rows):
        return {'game_id': schedule['game_id'], 'season': schedule['season'], 'date': schedule['gameday'],
                'blockers': ['missing_order'], 'labels': [], 'families': {}}
    rows.sort(key=lambda r: r['order_sequence'])
    if len({r['order_sequence'] for r in rows}) != len(rows) or len({r['play_id'] for r in rows}) != len(rows):
        reasons.add('duplicate_order_or_play')
    if rows[0].get('play_type_nfl') != 'GAME_START' or rows[-1].get('play_type_nfl') != 'END_GAME':
        reasons.add('missing_game_boundary')
    if not {1, 2, 3, 4} <= {r.get('qtr') for r in rows}:
        reasons.add('missing_quarter')
    if any(rows[-1].get('total_' + side + '_score') != schedule.get(side + '_score')
           or schedule.get(side + '_score') is None for side in ('home', 'away')):
        reasons.add('final_score_mismatch')
    previous_q, previous_clock = 0, 900
    for row in rows:
        q, clock = row.get('qtr'), row.get('quarter_seconds_remaining')
        if not number(q) or not number(clock) or q < 1 or not 0 <= clock <= 900:
            reasons.add('invalid_period_clock')
            continue
        if q < previous_q or (q == previous_q and clock > previous_clock):
            reasons.add('clock_regression')
        previous_q, previous_clock = q, clock
        if row.get('play_type') == 'no_play' or row.get('two_point_attempt') == 1:
            continue
        # Do not discard unaffected stat families. A lateral pass does not
        # invalidate rushing attempts; ambiguous receiving allocation stays out.
        affected = set()
        if row.get('lateral_reception') == 1:
            affected.update(('receiving_yards', 'receptions', 'passing_yards'))
        if row.get('lateral_rush') == 1:
            affected.update(('rushing_yards', 'carries'))
        if row.get('lateral_recovery') == 1:
            affected.update(FIELDS)
        for stat in affected:
            family_reasons[stat].add('lateral_allocation_unvalidated')
        for stat, (identity, value_field) in FIELDS.items():
            value, player = row.get(value_field), row.get(identity)
            if value is None or value == 0:
                continue
            if not number(value) or not player:
                family_reasons[stat].add('missing_identity_or_value')
                continue
            totals[(player, stat)] += int(value)
            quarters[(player, stat)][int(q)] += int(value)
        if row.get('touchdown') == 1:
            if not row.get('td_player_id'):
                reasons.add('missing_touchdown_scorer')
            touchdowns.append(row.get('td_player_id'))
    by_player = {}
    for row in box:
        player = row.get('player_id')
        if not player or player in by_player:
            reasons.add('duplicate_or_missing_box_player')
        by_player[player] = row
    families = {}
    for stat in FIELDS:
        mismatches = []
        for player in set(by_player) | {p for p, s in totals if s == stat}:
            expected = by_player.get(player, {}).get(stat)
            derived = totals.get((player, stat), 0)
            if not number(expected) or expected != derived:
                mismatches.append({'player_id': player, 'final': expected, 'derived': derived})
        passed = bool(box) and not reasons and not family_reasons[stat] and not mismatches
        families[stat] = {'reconciled': passed, 'mismatches': mismatches,
                          'blockers': sorted(family_reasons[stat])}
        if not passed:
            continue
        for player, final in by_player.items():
            # Evaluation population is explicitly conditional on recorded
            # offensive participation, never interpreted as a pregame roster.
            if final.get('position') not in ('QB', 'RB', 'FB', 'WR', 'TE'):
                continue
            periods = quarters[(player, stat)]
            values = {f'{q}q_{stat}': periods.get(q, 0) for q in range(1, 5)}
            values['1h_' + stat] = periods.get(1, 0) + periods.get(2, 0)
            values['2h_reg_' + stat] = periods.get(3, 0) + periods.get(4, 0)
            for market, value in values.items():
                labels.append({'player_id': player, 'market': market, 'value': value})
    # Offensive scorer labels require all TD types to be reconciled. Do not
    # quietly omit defensive/special-team or unlisted scorers from the sequence.
    scorer_mismatches = []
    for player in set(by_player) | set(touchdowns):
        b = by_player.get(player, {})
        counts = [b.get(k) for k in ('rushing_tds', 'receiving_tds', 'special_teams_tds', 'def_tds')]
        if not all(number(v) for v in counts) or sum(counts) != touchdowns.count(player):
            scorer_mismatches.append(player)
    scorer_ready = bool(box) and not reasons and not scorer_mismatches
    if scorer_ready:
        for player, final in by_player.items():
            if final.get('position') in ('QB', 'RB', 'FB', 'WR', 'TE'):
                for market, index in (('first_td_scorer', 0), ('last_td_scorer', -1)):
                    labels.append({'player_id': player, 'market': market,
                                   'value': int(bool(touchdowns) and touchdowns[index] == player)})
    return {'game_id': schedule['game_id'], 'season': schedule['season'],
            'date': schedule['gameday'], 'blockers': sorted(reasons), 'families': families,
            'scorer_reconciled': scorer_ready, 'scorer_mismatches': scorer_mismatches,
            'labels': labels}
