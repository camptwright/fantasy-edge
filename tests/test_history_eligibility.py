from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from src.models.identity import Player
from src.models.facts import Game, PlayerGameStat
from src.services.projections import project_stats
from src.ingest.result_repair import due_games
from src.ingest.identity import resolve_verified_espn_team
import pytest


async def test_preseason_unknown_time_future_and_unfinished_excluded(db):
    p = Player(sport='mlb', full_name='Eligibility Fixture')
    db.add(p)
    await db.flush()
    now = datetime.now(timezone.utc)
    for i in range(8):
        game = Game(sport='mlb', season=2026, status='final', game_type='REG',
                    mlb_game_pk=str(1000+i), game_time=now-timedelta(days=i+1))
        if i == 4:
            game.game_type = 'PRE'
        elif i == 5:
            game.game_time = None
        elif i == 6:
            game.game_time = now+timedelta(days=1)
        elif i == 7:
            game.status = 'scheduled'
        db.add(game)
        await db.flush()
        db.add(PlayerGameStat(player_id=p.id, game_id=game.id, stat_type='hits', value=i if i < 4 else 999))
    await db.flush()
    result = await project_stats(db, {(p.id, 'hits')})
    assert result[(p.id, 'hits')][0] == 1.5
    due = await due_games(db, 'mlb', 'mlb_stats_api', Game.mlb_game_pk, 20, now)
    assert all(g.game_type != 'PRE' for g in due)
    assert any(g.game_time is None for g in due)  # unknown time stays reviewable
    assert len((await db.scalars(select(PlayerGameStat))).all()) == 8  # facts retained


async def test_native_team_identity_is_idempotent_and_abbreviation_collision_rejected(db):
    metadata = {'id': '99001', 'displayName': 'Verified Opponent', 'abbreviation': 'VOP'}
    first = await resolve_verified_espn_team(db, metadata, 'ncaaf')
    second = await resolve_verified_espn_team(db, metadata, 'ncaaf')
    assert first.id == second.id
    with pytest.raises(ValueError):
        await resolve_verified_espn_team(db, {**metadata, 'id': '99002'}, 'ncaaf')
