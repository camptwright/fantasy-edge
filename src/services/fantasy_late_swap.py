"""Roster-only conditional substitutions for uncertain starters before kickoff."""
from datetime import datetime, timezone
from math import isfinite

from src.services.availability_status import normalize_status, confirmed_absent

FLEX = {'FLEX': {'RB', 'WR', 'TE'}, 'SUPER_FLEX': {'QB', 'RB', 'WR', 'TE'},
        'WRRB_FLEX': {'WR', 'RB'}, 'REC_FLEX': {'WR', 'TE'}, 'OP': {'QB', 'RB', 'WR', 'TE'}}


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def numeric(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def plans(roster_players, starters, *, now=None):
    """A final designation must be checked before the starter locks; no transactions."""
    now = now or datetime.now(timezone.utc)
    by_id = {str(p['player_id']): p for p in roster_players}
    starting = {str(s.get('player_id')) for s in starters if s.get('player_id')}
    output, blockers = [], []
    for slot in starters:
        player = by_id.get(str(slot.get('player_id')))
        if not player or normalize_status(player.get('injury_status')) not in ('QUESTIONABLE', 'DOUBTFUL'):
            continue
        kickoff = timestamp(player.get('week_kickoff'))
        if player.get('locked') or player.get('week_game_status') != 'scheduled' or not kickoff or kickoff <= now:
            blockers.append({'player_id': player['player_id'], 'reason': 'starter_locked_or_unknown_kickoff'})
            continue
        positions = FLEX.get(slot['slot'], {slot['slot'].rstrip('0123456789')})
        if 'DEF' in positions or 'DST' in positions:
            positions = {'DEF', 'DST'}
        replacements = []
        for candidate in roster_players:
            other_kickoff = timestamp(candidate.get('week_kickoff'))
            if (str(candidate['player_id']) in starting or candidate.get('reserve_slot') or
                    candidate.get('locked') or candidate.get('position') not in positions or
                    confirmed_absent(candidate.get('injury_status')) or
                    normalize_status(candidate.get('injury_status')) in ('QUESTIONABLE', 'DOUBTFUL') or
                    candidate.get('game_availability_hold') or candidate.get('week_game_status') != 'scheduled' or
                    not other_kickoff or other_kickoff < kickoff or other_kickoff <= now or
                    not numeric(candidate.get('points'))):
                continue
            replacements.append(candidate)
        if not replacements:
            blockers.append({'player_id': player['player_id'], 'reason': 'no_eligible_later_bench_projection'})
            continue
        replacement = sorted(replacements, key=lambda p: (-p['points'], str(p['player_id'])))[0]
        rate, starter_points = player.get('play_probability'), player.get('points')
        risk_points = (rate * starter_points + (1-rate) * replacement['points']
                       if not player.get('game_availability_hold') and numeric(rate) and 0 <= rate <= 1 and numeric(starter_points) else None)
        output.append({'starter_id': player['player_id'], 'starter_name': player['name'], 'slot': slot['slot'],
            'replacement_id': replacement['player_id'], 'replacement_name': replacement['name'],
            'replacement_points': replacement['points'], 'projection_source': replacement.get('source', 'unknown'),
            'check_by': kickoff.isoformat(), 'replacement_kickoff': replacement['week_kickoff'],
            'availability_trigger': 'final_inactive_designation_checked_before_starter_kickoff',
            'risk_adjusted_points': round(risk_points, 2) if risk_points is not None else None})
    # Each starter's contingency is independent; the same backup cannot cover both together.
    return {'status': 'conditional_plans' if output else 'no_eligible_plan', 'plans': output, 'blockers': blockers}
