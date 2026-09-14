"""Research-only Core play attribution. Never writes settlement or model facts."""
from collections import defaultdict
from copy import deepcopy
import re
from urllib.parse import urlparse

from src.services.football_pbp_validation import audit, integer


def athlete_id(participant, league):
    ref = urlparse(participant['athlete']['$ref'])
    if ref.scheme not in ('http', 'https') or ref.netloc != 'sports.core.api.espn.com':
        raise ValueError('untrusted athlete reference')
    match = re.fullmatch(r'/v2/sports/football/leagues/' + re.escape(league)
                         + r'/seasons/\d+/athletes/(\d+)', ref.path)
    if not match:
        raise ValueError('wrong athlete reference scope')
    return match[1]


def reconcile(core, summary, event_id, league, boxscore, evidence=None):
    """Use complete provider list order, independently checked against score/clock.

    Inline participant stats are deliberately ignored: college feeds embed game
    totals there. Unsupported/penalty plays remain explicit unresolved evidence.
    """
    blockers, unresolved, scorers, resolved = set(), [], [], []
    evidence = evidence or {}
    totals, periods = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    items = core.get('items', [])
    if (core.get('pageCount') != 1 or core.get('pageIndex') != 1
            or core.get('count') != len(items) or not items):
        blockers.add('incomplete_core_page')
    ref = urlparse(core.get('$ref', ''))
    expected_path = f'/v2/sports/football/leagues/{league}/events/{event_id}/competitions/{event_id}/plays'
    if ref.netloc != 'sports.core.api.espn.com' or ref.path != expected_path:
        blockers.add('wrong_core_event')
    # Preserve API order, not sequenceNumber: college sequences can restart.
    ordered = deepcopy(items)
    ids = [str(p.get('id')) for p in ordered]
    if len(set(ids)) != len(ids):
        blockers.add('duplicate_core_play')
    tied = defaultdict(list)
    for play in items:
        tied[(str(play.get('sequenceNumber')), str(play.get('period')),
              str(play.get('clock')))].append(play)
    for group in tied.values():
        if len(group) > 1 and sum(p.get('scoringPlay') is True for p in group) > 1:
            blockers.add('ambiguous_scoring_sequence')
    for index, play in enumerate(ordered):
        play['sequenceNumber'] = str(index)
    proxy = deepcopy(summary)
    proxy['drives'] = {'previous': [{'plays': ordered}]}
    timeline = audit(proxy, event_id)
    blockers.update(timeline['timeline_blockers'])
    for play in items:
        try:
            pid, kind = str(play['id']), play['type']['text']
            period = integer(play['period']['number'])
            roles = defaultdict(set)
            for participant in play.get('participants', []):
                roles[participant['type']].add(athlete_id(participant, league))

            def one(role):
                if len(roles[role]) != 1:
                    raise ValueError('ambiguous or missing ' + role)
                return next(iter(roles[role]))

            def add(player, stat, value):
                totals[player][stat] += value
                periods[(player, stat)][period] += value

            if play.get('scoringPlay') is True and 'Touchdown' in kind:
                scorers.append({'play_id': pid, 'athlete_id': one('scorer'), 'period': period})
            if play.get('isPenalty') is True or kind in ('Penalty', 'Fumble', 'Fumble Recovery (Own)'):
                # An accepted penalty can coexist with a counted play. Require
                # explicit per-play deltas for every relevant offensive role.
                from src.services.football_play_evidence import parse_evidence
                pending = []
                categories = {'passer': 'passing', 'receiver': 'receiving', 'rusher': 'rushing'}
                for role, category in categories.items():
                    for player in roles.get(role, set()):
                        key = f'{pid}:{player}'
                        if key not in evidence:
                            raise ValueError('missing per-play evidence')
                        values = parse_evidence(evidence[key], league, event_id, pid, player, category)
                        pending.extend((player, stat, value) for stat, value in values.items())
                if pending:
                    for player, stat, value in pending:
                        add(player, stat, value)
                    resolved.append(pid)
                    continue
                unresolved.append({'play_id': pid, 'reason': 'penalty_or_fumble_requires_stat_evidence'})
                continue
            if kind in ('Pass Reception', 'Passing Touchdown'):
                passer, receiver = one('passer'), one('receiver')
                yards = integer(play['statYardage'])
                for player, stat, value in ((passer, 'passing_yards', yards),
                        (passer, 'passing_completions', 1), (passer, 'passing_attempts', 1),
                        (receiver, 'receiving_yards', yards), (receiver, 'receptions', 1),
                        (passer, 'passing_touchdowns', int(kind == 'Passing Touchdown')),
                        (receiver, 'receiving_touchdowns', int(kind == 'Passing Touchdown'))):
                    add(player, stat, value)
            elif kind in ('Rush', 'Rushing Touchdown'):
                player = one('rusher')
                for stat, value in (('rushing_yards', integer(play['statYardage'])),
                                    ('rushing_attempts', 1), ('rushing_touchdowns', int(kind == 'Rushing Touchdown'))):
                    add(player, stat, value)
            elif kind in ('Pass Incompletion', 'Pass Interception Return'):
                add(one('passer'), 'passing_attempts', 1)
            elif kind == 'Sack' and league == 'college-football':
                unresolved.append({'play_id': pid, 'reason': 'college_sack_rushing_allocation'})
            elif kind not in ('Sack', 'Rush', 'Rushing Touchdown', 'Pass Reception',
                              'Passing Touchdown', 'Pass Incompletion', 'Pass Interception Return') and (
                    roles.get('passer') or roles.get('receiver') or roles.get('rusher')):
                unresolved.append({'play_id': pid, 'reason': 'unsupported_offensive_play_type'})
        except (KeyError, ValueError, TypeError, AttributeError):
            unresolved.append({'play_id': str(play.get('id')), 'reason': 'invalid_structured_attribution'})
    supported = {'passing_yards', 'passing_completions', 'passing_attempts', 'passing_touchdowns',
                 'receiving_yards', 'receptions', 'receiving_touchdowns', 'rushing_yards', 'rushing_attempts', 'rushing_touchdowns'}
    keys = {(p, s) for p, stats in boxscore.items() for s in stats if s in supported}
    keys.update((p, s) for p, stats in totals.items() for s in stats)
    comparisons = []
    for player, stat in sorted(keys):
        derived, final = totals.get(player, {}).get(stat), boxscore.get(player, {}).get(stat)
        state = ('missing_derived' if derived is None else 'missing_boxscore' if final is None
                 else 'matched' if derived == final else 'mismatch')
        comparisons.append({'athlete_id': player, 'stat': stat, 'derived': derived,
                            'final': final, 'state': state})
    family_checks = {}
    for stat in sorted(supported):
        rows = [r for r in comparisons if r['stat'] == stat]
        family_checks[stat] = {'compared_players': len(rows),
            'all_totals_match': bool(rows) and all(r['state'] == 'matched' for r in rows)}
    serving_blockers = ['settlement_rules_not_validated', 'period_scorer_model_not_evaluated',
                        'insufficient_validated_historical_games']
    if blockers:
        serving_blockers.append('timeline_evidence_incomplete')
    if unresolved:
        serving_blockers.append('unresolved_play_statistics')
    if any(r['state'] != 'matched' for r in comparisons):
        serving_blockers.append('player_boxscore_reconciliation_incomplete')
    return {'event_id': str(event_id), 'ordering_basis': 'complete_core_provider_list',
            'timeline_blockers': sorted(blockers), 'unresolved_plays': unresolved,
            'resolved_with_per_play_statistics': resolved,
            'stat_family_checks': family_checks, 'serving_blockers': serving_blockers,
            'comparisons': comparisons, 'scorers': scorers if not blockers else [],
            'period_candidates': [{'athlete_id': p, 'stat': s, 'periods': dict(v)}
                                  for (p, s), v in periods.items()],
            'player_prop_ready': False, 'serving_enabled': False,
            'note': 'Matching totals are necessary, not proof of correct period allocation or settlement.'}
