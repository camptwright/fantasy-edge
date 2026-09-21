"""Timestamped, reproducible player context for SHADOW research only.

No injury/news/playing-time fields are invented. Observed opportunity is not a
confirmed future role. Historical publication timestamps remain unavailable.
"""
import math
import statistics
from collections import defaultdict
from sqlalchemy import select, or_
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.models.ratings import TeamRating
from src.services.stat_identity import canonical_results, canonical_stat, ALIASES
from src.services.result_eligibility import no_pending_correction

OPPORTUNITY = {'passing_yards': 'passing_attempts', 'passing_completions': 'passing_attempts', 'passing_touchdowns': 'passing_attempts',
    'passing_interceptions': 'passing_attempts', 'rushing_yards': 'rushing_attempts',
    'rushing_touchdowns': 'rushing_attempts', 'receiving_yards': 'receptions',
    'receiving_touchdowns': 'receptions', 'hits': 'plate_appearances', 'home_runs': 'plate_appearances',
    'points': 'minutes', 'rebounds': 'minutes', 'assists': 'minutes', 'blocks': 'minutes', 'steals': 'minutes',
    'goals': 'shots_on_goal'}


def profile(rows):
    if len(rows) < 4:
        return None
    values = [r[2] for r in sorted(rows)]
    return {'games': len(values), 'mean': statistics.fmean(values),
        'variance': statistics.pvariance(values), 'recent_mean': statistics.fmean(values[-5:]),
        'recent_games': min(5, len(values))}


async def snapshots(db, props, as_of):
    ids = {p['player_id'] for p in props}
    if not ids:
        return {}
    import uuid
    players = {str(p.id): p for p in (await db.scalars(select(Player).where(
        Player.id.in_([uuid.UUID(x) for x in ids])))).all()}
    event_ids = {uuid.UUID(p['game_id']) for p in props if p.get('game_id')}
    events = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_(event_ids)))).all()} if event_ids else {}
    team_ids = {t for g in events.values() for t in (g.home_team_id, g.away_team_id) if t}
    ratings = {r.team_id: r for r in (await db.scalars(select(TeamRating).where(TeamRating.team_id.in_(team_ids)))).all()} if team_ids else {}
    needed = {canonical_stat(p['stat_type']) for p in props} | set(OPPORTUNITY.values()) | {'targets', 'fg_made', 'xp_made'}
    needed |= {alias for alias, canonical in ALIASES.items() if canonical in needed}
    rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id,
        PlayerGameStat.stat_type, PlayerGameStat.value, Game.game_time).join(Game, Game.id == PlayerGameStat.game_id)
        .join(Player, Player.id == PlayerGameStat.player_id)
        .where(PlayerGameStat.player_id.in_([uuid.UUID(x) for x in ids]), Game.status == 'final',
               Game.sport == Player.sport,
               PlayerGameStat.stat_type.in_(needed),
               no_pending_correction(),
               or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
               Game.game_time.isnot(None), Game.game_time < as_of))).all()
    # Unknown-time history stays in storage, but cannot enter an as-of feature.
    times = {row.game_id: row.game_time for row in rows}
    history = defaultdict(list)
    for (player, game, stat), value in canonical_results(rows).items():
        if math.isfinite(value):
            history[(str(player), stat)].append((times[game], str(game), value))
    result = {}
    for p in props:
        stat, player = canonical_stat(p['stat_type']), p['player_id']
        h = sorted(history.get((player, stat), []))
        basic = profile(h)
        if basic is None:
            continue
        usage_stat = OPPORTUNITY.get(stat)
        if stat in ('receiving_yards', 'receiving_touchdowns', 'receptions') and len(history.get((player, 'targets'), [])) >= 4:
            usage_stat = 'targets'
        usage = sorted(history.get((player, usage_stat), [])) if usage_stat else []
        usage_by_game = {r[1]: r[2] for r in usage}
        paired = [(value, usage_by_game[game]) for _, game, value in h[-10:]
                  if game in usage_by_game and usage_by_game[game] >= 0]
        opportunity = None
        if len(paired) >= 4 and sum(u for _, u in paired) > 0 and len(usage) >= 4:
            opportunity = {'stat': usage_stat, 'paired_games': len(paired),
                'recent_mean': statistics.fmean(r[2] for r in usage[-5:]),
                'observed_rate': sum(v for v, _ in paired)/sum(u for _, u in paired),
                'receptions_proxy_not_targets': usage_stat == 'receptions',
                'is_confirmed_future_role': False}
        event, identity = events.get(p.get('game_id')), players.get(player)
        opponent_id, is_home = None, None
        if event and identity and identity.current_team_id:
            if identity.current_team_id == event.home_team_id:
                opponent_id, is_home = event.away_team_id, True
            elif identity.current_team_id == event.away_team_id:
                opponent_id, is_home = event.home_team_id, False
        opponent = ratings.get(opponent_id)
        context = {'game_id': p.get('game_id'), 'position': identity.position if identity else None,
            'is_home': is_home, 'opponent_team_id': str(opponent_id) if opponent_id else None,
            'opponent_rating': opponent.rating if opponent else None,
            'opponent_points_allowed': opponent.avg_points_allowed if opponent else None,
            'opponent_history_games': opponent.games_played if opponent else None,
            'opponent_rating_updated_at': opponent.updated_at.isoformat() if opponent else None,
            'used_for_numeric_adjustment': False}
        result[p['id']] = {**basic, 'as_of': as_of.isoformat(), 'canonical_stat': stat,
            'last_result_at': h[-1][0].isoformat(), 'days_since_last_result': (as_of-h[-1][0]).total_seconds()/86400,
            'recent_minus_history_mean': basic['recent_mean']-basic['mean'], 'opportunity': opportunity,
            'event_context': context,
            'components': {s: profile(history.get((player, s), [])) for s in ('fg_made', 'xp_made')}
                if stat == 'kicking_points' else {},
            'missing_context': ['confirmed_lineup', 'injury_status', 'timestamped_weather', 'news_features',
                                'opponent_adjustment'],
            'history_publication_timestamps_available': False}
    return result
