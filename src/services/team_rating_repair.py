"""Transactional chronological replay after a provider changes a final score.

Reuse the retained Elo math. No extra incremental application, season reset,
or forecast rewrite. Store before/after ratings for audit in ingestion_runs.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import select, text
from src.models.facts import Game
from src.models.ratings import TeamRating, STARTING_RATING
from src.models.governance import IngestionRun
from src.services.elo import apply_result, update_scoring_average


async def lock_sport(db, sport):
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                     {'key': 'team-rating:' + sport})


async def repair_changed_score(db, game, old_score, *, retry=False):
    if game.status not in ('final', 'cancelled') or (game.status == 'final' and not retry and old_score == (game.home_score, game.away_score)):
        return
    await lock_sport(db, game.sport)
    games = (await db.scalars(select(Game).where(Game.sport == game.sport,
        Game.status == 'final').order_by(Game.game_time.asc().nulls_last(), Game.id))).all()
    now = datetime.now(timezone.utc)
    detail = {'sport': game.sport, 'trigger_game_id': str(game.id), 'old_score': old_score,
              'new_score': [game.home_score, game.away_score], 'games': len(games)}
    # No replay on an incomplete chronological history: preserve current ratings.
    if any(g.game_time is None or g.game_time > now or g.home_team_id is None or
           g.away_team_id is None or g.home_score is None or g.away_score is None for g in games):
        detail['reason'] = 'incomplete_final_history'
        db.add(IngestionRun(source='team_rating_repair', status='deferred', started_at=now,
            finished_at=now, rows_written=0, detail=json.dumps(detail)))
        return
    ratings = {r.team_id: r for r in (await db.scalars(select(TeamRating).where(
        TeamRating.sport == game.sport).with_for_update())).all()}
    def view(r):
        return dict(rating=r.rating, games_played=r.games_played,
                    avg_points_scored=r.avg_points_scored, avg_points_allowed=r.avg_points_allowed)
    detail['before'] = {str(k): view(r) for k, r in ratings.items()}
    states = {}
    for g in games:
        for tid in (g.home_team_id, g.away_team_id):
            states.setdefault(tid, SimpleNamespace(rating=STARTING_RATING, games_played=0,
                avg_points_scored=None, avg_points_allowed=None))
        home, away = states[g.home_team_id], states[g.away_team_id]
        home.rating, away.rating = apply_result(home.rating, away.rating, g.home_score, g.away_score)
        update_scoring_average(home, scored=g.home_score, allowed=g.away_score)
        update_scoring_average(away, scored=g.away_score, allowed=g.home_score)
    for tid, state in states.items():
        target = ratings.get(tid)
        if target is None:
            target = TeamRating(team_id=tid, sport=game.sport)
            db.add(target)
        for key, value in view(state).items():
            setattr(target, key, value)
    detail['after'] = {str(k): view(r) for k, r in states.items()}
    db.add(IngestionRun(source='team_rating_repair', status='succeeded', started_at=now,
        finished_at=datetime.now(timezone.utc), rows_written=len(states), detail=json.dumps(detail)))
    await db.flush()


async def retry_deferred(db):
    from config.settings import get_settings
    import uuid
    retried = []
    for sport in get_settings().supported_sports:
        await lock_sport(db, sport)
        # One durable latest audit per sport. A successful replay closes older deferrals.
        latest = await db.scalar(select(IngestionRun).where(
            IngestionRun.source == 'team_rating_repair',
            IngestionRun.detail.contains('"sport": "' + sport + '"'))
            .order_by(IngestionRun.started_at.desc(), IngestionRun.id).limit(1))
        if latest and latest.status == 'deferred':
            info = json.loads(latest.detail)
            game = await db.get(Game, uuid.UUID(info['trigger_game_id']))
            if game is not None:
                await repair_changed_score(db, game, info['old_score'], retry=True)
                retried.append(sport)
        await db.commit()
    return {'retried_sports': retried}
