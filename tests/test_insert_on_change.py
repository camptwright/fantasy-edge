"""Line tables are append-only and write on change, not on poll.

Polling every five minutes while a line sits still would otherwise write
garbage. Note there is deliberately NO unique index enforcing this: a line
can move away and come back (-3 -> -3.5 -> -3), and that return is real
movement. A unique constraint would wrongly reject it, so the check is
application-level and this test is what protects it.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.ingest.lines import record_team_line
from src.models.facts import Game, TeamMarketLine
from src.models.identity import Team  # noqa: F401 - registers `teams` for the games FK


async def _game(db) -> Game:
    game = Game(season=2026, week=1, status="scheduled")
    db.add(game)
    await db.flush()
    return game


async def _count(db, game) -> int:
    return await db.scalar(
        select(func.count()).select_from(TeamMarketLine).where(TeamMarketLine.game_id == game.id)
    )


async def test_unchanged_line_writes_nothing_on_second_poll(db):
    game = await _game(db)
    kwargs = dict(
        game_id=game.id, market="spread", side="home", line=-3.0,
        price_american=-110, source="espn", line_type="live",
    )
    assert await record_team_line(db, **kwargs) is True
    assert await record_team_line(db, **kwargs) is False
    assert await _count(db, game) == 1


async def test_moved_line_writes_a_new_row(db):
    game = await _game(db)
    base = dict(
        game_id=game.id, market="spread", side="home",
        price_american=-110, source="espn", line_type="live",
    )
    await record_team_line(db, line=-3.0, **base)
    await record_team_line(db, line=-3.5, **base)
    assert await _count(db, game) == 2


async def test_price_move_alone_writes_a_new_row(db):
    game = await _game(db)
    base = dict(
        game_id=game.id, market="spread", side="home", line=-3.0,
        source="espn", line_type="live",
    )
    await record_team_line(db, price_american=-110, **base)
    await record_team_line(db, price_american=-115, **base)
    assert await _count(db, game) == 2


async def test_line_returning_to_a_previous_value_is_recorded(db):
    """-3 -> -3.5 -> -3 is three real observations, not two."""
    game = await _game(db)
    base = dict(
        game_id=game.id, market="spread", side="home",
        price_american=-110, source="espn", line_type="live",
    )
    await record_team_line(db, line=-3.0, **base)
    await record_team_line(db, line=-3.5, **base)
    await record_team_line(db, line=-3.0, **base)
    assert await _count(db, game) == 3


async def test_sources_do_not_suppress_each_other(db):
    game = await _game(db)
    base = dict(
        game_id=game.id, market="spread", side="home", line=-3.0,
        price_american=-110, line_type="live",
    )
    assert await record_team_line(db, source="espn", **base) is True
    assert await record_team_line(db, source="theodds", **base) is True
    assert await _count(db, game) == 2
