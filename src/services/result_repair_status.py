"""Read-only outcome repair telemetry; counts are not model accuracy claims."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from src.models.facts import Game, PlayerGameStat
from src.models.governance import IngestionRun, ResultCorrection, ResultSyncState


async def status(db):
    now = datetime.now(timezone.utc)
    states = (await db.execute(select(Game.sport, ResultSyncState.status, func.count())
        .join(Game, Game.id == ResultSyncState.game_id).group_by(Game.sport, ResultSyncState.status))).all()
    corrections = (await db.execute(select(ResultCorrection.status, func.count())
        .group_by(ResultCorrection.status))).all()
    latest = (await db.execute(select(ResultCorrection, PlayerGameStat, Game.sport)
        .join(PlayerGameStat, PlayerGameStat.id == ResultCorrection.stat_id)
        .join(Game, Game.id == PlayerGameStat.game_id)
        .order_by(ResultCorrection.last_seen_at.desc()).limit(50))).all()
    return {'observed_at': now.isoformat(),
        'team_rating_repairs': [{'status': r.status, 'started_at': r.started_at.isoformat(),
             'teams_written': r.rows_written} for r in (await db.scalars(select(IngestionRun).where(
             IngestionRun.source == 'team_rating_repair').order_by(IngestionRun.started_at.desc()).limit(10))).all()],
        'games_by_status': [{'sport': sport, 'status': state, 'games': count} for sport, state, count in states],
        'due_tracked_games': await db.scalar(select(func.count()).select_from(ResultSyncState)
            .where(ResultSyncState.next_attempt_at <= now)),
        'correction_counts': dict(corrections),
        'recent_corrections': [{'sport': sport, 'game_id': str(fact.game_id), 'player_id': str(fact.player_id),
            'stat': fact.stat_type, 'provider': c.provider, 'event_id': c.event_id,
            'old_value': c.old_value, 'new_value': c.new_value, 'status': c.status,
            'first_seen_at': c.first_seen_at.isoformat(), 'last_seen_at': c.last_seen_at.isoformat(),
            'applied_at': c.applied_at.isoformat() if c.applied_at else None} for c, fact, sport in latest],
        'policy': 'All five sports: partial/deferred/confirming retries hourly; successful recent games every six hours; '
                  'older successes weekly. Corrections require two observations at least 30 minutes apart. '
                  'Missing fields never become zero. Forecasts remain immutable; grading reads current facts.'}
