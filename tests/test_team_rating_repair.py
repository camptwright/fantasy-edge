from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.models.identity import Team
from src.models.facts import Game
from src.models.ratings import TeamRating
from src.models.governance import IngestionRun
from src.services.elo import update_ratings_after_game, apply_result
from src.services.team_rating_repair import repair_changed_score


async def test_corrected_final_replays_in_order_without_double_counting(db):
    a, b = Team(sport='nfl', name='Replay A', espn_id='replay-a', nflverse_abbr='RA'), Team(sport='nfl', name='Replay B', espn_id='replay-b', nflverse_abbr='RB')
    db.add_all([a, b])
    await db.flush()
    games = []
    for i in range(2):
        g = Game(sport='nfl', season=2026, status='final', home_team_id=a.id, away_team_id=b.id,
                 home_score=20, away_score=10, game_time=datetime.now(timezone.utc)-timedelta(days=2-i))
        db.add(g)
        await db.flush()
        await update_ratings_after_game(db, g)
        games.append(g)
    games[0].home_score = 0
    await db.flush()
    await repair_changed_score(db, games[0], (20, 10))
    home = await db.scalar(select(TeamRating).where(TeamRating.team_id == a.id))
    first = apply_result(1500, 1500, 0, 10)
    expected = apply_result(*first, 20, 10)
    assert home.rating == expected[0]
    assert home.games_played == 2 and home.avg_points_scored == 10
    await repair_changed_score(db, games[0], (0, 10))
    assert len((await db.scalars(select(IngestionRun))).all()) == 1


async def test_incomplete_final_history_defers_without_replacing_ratings(db):
    game = Game(sport='nfl', season=2026, status='final', home_score=10, away_score=3)
    db.add(game)
    await db.flush()
    await repair_changed_score(db, game, (7, 3))
    assert (await db.scalar(select(IngestionRun))).status == 'deferred'
    assert not (await db.scalars(select(TeamRating))).all()
