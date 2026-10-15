"""Observed role history, with absent measurements left unknown."""
from datetime import datetime, timezone
from statistics import fmean
from sqlalchemy import select, or_
from src.models.facts import Game, PlayerGameStat, PlayerSnapCount
from src.models.governance import ResultCorrection
from src.services.dynasty_trade_planning import number

METRICS = ('snap_share', 'targets', 'carries', 'target_share', 'carry_share', 'red_zone_targets', 'red_zone_carries')


def summarize(rows):
    rows = sorted(rows, key=lambda r: (r['kickoff'], r['game_id']))[-6:]
    if len({r['game_id'] for r in rows}) != len(rows):
        return {'status': 'ambiguous_game_history', 'games': [], 'trends': {}}
    trends = {}
    recent, prior = rows[-3:], rows[:-3]
    for metric in METRICS:
        a = [r[metric] for r in recent if number(r.get(metric))]
        b = [r[metric] for r in prior if number(r.get(metric))]
        trends[metric] = {'recent': round(fmean(a), 4) if a else None,
                          'prior': round(fmean(b), 4) if b else None,
                          'change': round(fmean(a) - fmean(b), 4) if len(a) == 3 and len(b) == 3 else None,
                          'recent_games': len(a), 'prior_games': len(b)}
    return {'status': 'observed_history' if rows else 'missing_history', 'games': rows, 'trends': trends,
            'comparison': 'last_three_vs_previous_three_games',
            'note': 'Observed participation and usage; changes describe history and do not independently adjust forecasts. Missing measurements remain unknown.'}


async def profile(db, canonical_player_id, *, now=None, season=None):
    now = now or datetime.now(timezone.utc)
    filters = [Game.sport == 'nfl', Game.status == 'final', Game.game_time.is_not(None),
               Game.game_time < now, or_(Game.game_type.is_(None), Game.game_type == 'REG')]
    if season is not None:
        filters.append(Game.season == season)
    snaps = (await db.execute(select(PlayerSnapCount, Game).join(Game, Game.id == PlayerSnapCount.game_id).where(
        *filters, PlayerSnapCount.player_id == canonical_player_id,
        PlayerSnapCount.observed_at <= now).order_by(Game.game_time.desc(), PlayerSnapCount.observed_at.desc()).limit(20))).all()
    # Agreeing duplicate sources are safe; disagreements are shown as ambiguous.
    groups = {}
    for snap, game in snaps:
        groups.setdefault(game.id, []).append((snap, game))
    if any(len({(s.team_id, s.offense_snaps, s.offense_pct) for s, _ in members}) > 1 for members in groups.values()):
        return {'status': 'conflicting_snap_sources', 'games': [], 'trends': {}}
    selected = [members[0] for members in groups.values()][:6]
    disputed = set((await db.scalars(select(PlayerGameStat.game_id).join(ResultCorrection,
        ResultCorrection.stat_id == PlayerGameStat.id).where(
        PlayerGameStat.player_id == canonical_player_id,
        PlayerGameStat.game_id.in_([g.id for _, g in selected]), ResultCorrection.status == 'pending'))).all()) if selected else set()
    selected = [(s, g) for s, g in selected if g.id not in disputed]
    stats = (await db.scalars(select(PlayerGameStat).where(
        PlayerGameStat.player_id == canonical_player_id,
        PlayerGameStat.game_id.in_([g.id for _, g in selected]),
        PlayerGameStat.stat_type.in_(['targets', 'rushing_attempts', 'red_zone_targets', 'red_zone_rushing_attempts'])))).all() if selected else []
    values = {(s.game_id, s.stat_type): s.value for s in stats}
    rows = []
    for snap, game in selected:
        # Ingestion stores nflverse's 0..1 fraction, never guessed from snaps.
        pct = snap.offense_pct
        rows.append({'game_id': str(game.id), 'team_id': str(snap.team_id), 'season': game.season, 'week': game.week,
                     'kickoff': game.game_time.isoformat(), 'observed_at': snap.observed_at.isoformat(), 'source': snap.source,
                     'offensive_snaps': snap.offense_snaps,
                     'snap_share': pct if number(pct) and pct <= 1 else None,
                     'targets': values.get((game.id, 'targets')), 'carries': values.get((game.id, 'rushing_attempts')),
                     'target_share': None, 'carry_share': None,
                     'red_zone_targets': values.get((game.id, 'red_zone_targets')),
                     'red_zone_carries': values.get((game.id, 'red_zone_rushing_attempts'))})
    out = summarize(rows)
    out['share_coverage'] = 'team_target_and_carry_denominators_not_verified'
    out['pending_correction_games_withheld'] = len(disputed)
    return out
