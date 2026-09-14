"""Research-only ESPN timeline checks; never produce player outcomes from text.

Score reconciliation cannot prove every non-scoring play is present. Passing
these checks does not authorize settlement or period player-prop predictions.
"""
import hashlib
import json


def integer(value):
    if isinstance(value, bool):
        raise ValueError('boolean numeric field')
    result = int(value)
    if str(result) != str(value):
        raise ValueError('noninteger field')
    return result


def audit(payload, event_id):
    blockers = set()
    plays = {}
    touchdown_ids = []
    period_counts = {}
    try:
        competitions = payload['header']['competitions']
        competition = next(c for c in competitions if str(c['id']) == str(event_id))
        if competition['status']['type'].get('completed') is not True:
            blockers.add('not_final')
        sides = {c['homeAway']: c for c in competition['competitors']}
        if set(sides) != {'home', 'away'}:
            raise ValueError('missing competitors')
        final = tuple(integer(sides[s]['score']) for s in ('home', 'away'))
        expected = {s: [integer(x['displayValue']) for x in sides[s]['linescores']]
                    for s in ('home', 'away')}
        if any(len(v) != 4 for v in expected.values()):
            blockers.add('overtime_or_period_rules_unvalidated')
        drives = payload['drives']['previous']
        if not drives:
            raise ValueError('empty drives')
        for drive in drives:
            for p in drive['plays']:
                pid = str(p['id'])
                if not pid or (pid in plays and plays[pid] != p):
                    blockers.add('conflicting_play_id')
                plays[pid] = p
        ordered = sorted(plays.values(), key=lambda p: integer(p['sequenceNumber']))
        if not ordered:
            raise ValueError('empty plays')
        if ordered[0]['period'].get('number') != 1 or ordered[0]['clock'].get('displayValue') != '15:00':
            blockers.add('missing_regulation_start')
        sequences = [integer(p['sequenceNumber']) for p in ordered]
        if len(set(sequences)) != len(sequences):
            blockers.add('duplicate_sequence')
        previous_period, previous_clock = 0, 900
        previous_score = (0, 0)
        ends = {}
        for p in ordered:
            period = integer(p['period']['number'])
            clock_parts = p['clock']['displayValue'].split(':')
            if len(clock_parts) != 2 or not all(x.isdigit() for x in clock_parts):
                raise ValueError('invalid clock format')
            minutes, seconds = map(int, clock_parts)
            clock = minutes*60+seconds
            if period not in (1, 2, 3, 4):
                blockers.add('overtime_or_period_rules_unvalidated')
            if not (0 <= minutes <= 15 and 0 <= seconds < 60 and clock <= 900):
                blockers.add('invalid_clock')
            if period < previous_period or (period == previous_period and clock > previous_clock):
                blockers.add('clock_or_period_regression')
            score = (integer(p['homeScore']), integer(p['awayScore']))
            if any(v < old for v, old in zip(score, previous_score)):
                blockers.add('score_regression')
            ends[period] = score
            period_counts[period] = period_counts.get(period, 0)+1
            previous_score, previous_period, previous_clock = score, period, clock
        if set(period_counts) != {1, 2, 3, 4}:
            blockers.add('missing_or_extra_period')
        if ordered[-1]['type'].get('text') != 'End of Game':
            blockers.add('missing_end_game_marker')
        if previous_score != final:
            blockers.add('final_score_mismatch')
        before = (0, 0)
        for period in range(1, 5):
            end = ends.get(period)
            if end is None:
                continue
            for i, side in enumerate(('home', 'away')):
                if len(expected[side]) < period or end[i]-before[i] != expected[side][period-1]:
                    blockers.add('period_score_mismatch')
            before = end
        seen_scoring = set()
        for p in payload['scoringPlays']:
            pid = str(p['id'])
            if pid in seen_scoring or pid not in plays or plays[pid].get('scoringPlay') is not True:
                blockers.add('scoring_index_mismatch')
            seen_scoring.add(pid)
            if p.get('scoringType', {}).get('name') == 'touchdown':
                touchdown_ids.append(pid)
        rank = {str(p['id']): i for i, p in enumerate(ordered)}
        played_tds = {str(p['id']) for p in ordered if p.get('scoringPlay') is True
                      and 'touchdown' in p.get('type', {}).get('text', '').lower()}
        if played_tds != set(touchdown_ids):
            blockers.add('touchdown_index_mismatch')
        touchdown_ids.sort(key=lambda pid: rank.get(pid, -1))
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration, AttributeError):
        blockers.add('malformed_or_missing_required_evidence')
    return {'schema_version': 1, 'event_id': str(event_id),
        'payload_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        'timeline_checks_passed': not blockers, 'timeline_blockers': sorted(blockers),
        'unique_plays': len(plays), 'plays_by_period': period_counts,
        'touchdown_play_ids_in_order': touchdown_ids if not blockers else [],
        'player_prop_ready': False, 'serving_enabled': False,
        'remaining_requirements': ['structured_player_role_ids', 'complete_non_scoring_play_coverage',
            'player_totals_reconcile_to_final_boxscore', 'penalty_and_nullified_play_validation',
            'bookmaker_settlement_rules', 'prospective_period_model_validation'],
        'note': 'Timeline checks only. No player attribution inferred from prose; no outcomes or forecasts written.'}
