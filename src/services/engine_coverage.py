"""Coverage-aware engine inputs shared by fantasy research calculations."""
from src.services.fantasy_decision_models import optimize
from src.services.roster_stat_model import finite
from datetime import datetime, timedelta
from src.services.availability_status import normalize_status, ABSENT
from src.services.fantasy_schedule import coverage


def attach_coverage(players, games, schedule_coverage, week, now):
    """Attach trusted zero evidence without modifying existing projections.

    A missing game is a bye only in a validated complete regular season.
    Single-game absence applies only to the team's nearest scheduled game;
    long-term designations apply later, matching the depth engine's scope.
    """
    verified = coverage(games)
    complete = schedule_coverage.get('complete') is True and verified['complete']
    future = {}
    for game in games:
        if game.game_type != 'REG' or game.status != 'scheduled' or game.game_time is None or game.game_time <= now:
            continue
        for tid in (game.home_team_id, game.away_team_id):
            future.setdefault(str(tid), {}).setdefault(game.week, []).append(game)
    long_term = ABSENT - {'OUT', 'INACTIVE'}
    def recent(value, maximum):
        try:
            return timedelta(0) <= now - datetime.fromisoformat(value) <= maximum
        except (TypeError, ValueError):
            return False
    for player in players:
        engine = player.get('engine') or {}
        player['engine'] = engine
        team = player.get('nfl_team_id')
        states = []
        if complete and team:
            states += [{'week': w, 'status': 'verified_bye', 'reason': 'validated_17_game_regular_season'}
                       for w in verified['bye_weeks'].get(str(team), []) if w >= week]
        designation = normalize_status(player.get('injury_status'))
        fresh = recent(engine.get('generated_at'), timedelta(hours=3))
        metadata_fresh = recent(player.get('availability_observed_at'), timedelta(hours=24))
        if fresh and player.get('identity_status') == 'exact' and designation in ABSENT:
            events = future.get(str(team), {})
            near = min(events, default=None)
            for w, bound in events.items():
                if w < week or len(bound) != 1 or (w != near and designation not in long_term):
                    continue
                context = player.get('game_availability') or {}
                reports = {normalize_status(r.get('status')) for r in context.get('reports', []) if r.get('status')}
                if context.get('status') == 'conflicting_reports' or (reports and not reports <= ABSENT):
                    continue
                official = (context.get('official_game_status_verified') is True and
                            context.get('game_id') == str(bound[0].id) and
                            recent(context.get('observed_at'), timedelta(hours=3)))
                if not metadata_fresh and not official:
                    continue
                if not any(r.get('week') == w and finite(r.get('points')) for r in engine.get('weeks', [])):
                    states.append({'week': w, 'status': 'confirmed_unavailable',
                                   'reason': ('official_game_absence:' if official else 'provider_reported_absence:') + designation,
                                   'game_id': str(bound[0].id),
                                   'observed_at': context['observed_at'] if official else player['availability_observed_at']})
        # Recompute derived coverage on refresh; never preserve old absence rows.
        engine['coverage'] = sorted(states, key=lambda r: r['week'])
    return players


def week_state(player, week):
    engine = player.get('engine') or {}
    evidence = next((r for r in engine.get('coverage', []) if r.get('week') == week), {})
    if evidence.get('status') in ('verified_bye', 'confirmed_unavailable'):
        return {'status': evidence['status'], 'points': 0.0, 'reason': evidence.get('reason')}
    if engine.get('status') == 'research':
        rows = [r for r in engine.get('weeks', []) if r.get('week') == week]
        if len(rows) == 1 and finite(rows[0].get('points')):
            return {'status': 'projected', 'points': float(rows[0]['points'])}
    return {'status': 'missing_coverage', 'points': None, 'reason': engine.get('status')}


def solve(players, slots, week):
    states = {str(p['player_id']): week_state(p, week) for p in players}
    missing = [pid for pid, state in states.items() if state['points'] is None]
    rows = [{**p, 'name': p.get('name') or str(p['player_id']),
             'weekly_points': states[str(p['player_id'])]['points']} for p in players]
    result = optimize(rows, slots)
    if missing:
        result = {**result, 'status': 'missing_coverage', 'total': None}
    return {**result, 'missing_player_ids': missing, 'coverage': states}


def horizon(players, start_week=None, horizon_weeks=2):
    if type(horizon_weeks) is not int or not 2 <= horizon_weeks <= 4:
        raise ValueError('horizon_weeks must be between 2 and 4')
    observed = [r['week'] for p in players for r in (p.get('engine') or {}).get('weeks', [])
                if type(r.get('week')) is int]
    start = start_week if type(start_week) is int else min(observed, default=None)
    if start is not None and not 1 <= start <= 18:
        raise ValueError('start_week must be between 1 and 18')
    return list(range(start, min(19, start + horizon_weeks))) if start is not None else []
