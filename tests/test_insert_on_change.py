"""Line tables are append-only and write on change, not on poll.

Polling every five minutes while a line sits still would otherwise write
garbage. Note there is deliberately NO unique index enforcing this: a line
can move away and come back (-3 -> -3.5 -> -3), and that return is real
movement. A unique constraint would wrongly reject it, so the check is
application-level and this test is what protects it.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


async def test_tied_observed_at_resolves_deterministically(db):
    """`observed_at` defaults from a Python-side `datetime.now()` call (see
    src/models/base.py's `utcnow`), not a DB-generated monotonic sequence -
    two rows can in principle share a timestamp. This forces that tie
    directly (bypassing record_team_line's own timestamp generation) and
    checks the "latest" comparison consistently prefers the row with the
    higher `id` as its deterministic secondary sort key, rather than
    picking arbitrarily between the two tied rows.
    """
    game = await _game(db)
    tied_at = datetime.now(timezone.utc)
    common = dict(
        game_id=game.id, market="spread", side="home",
        price_american=-110, source="espn", line_type="live",
        observed_at=tied_at,
    )
    row_a = TeamMarketLine(line=-3.0, **common)
    row_b = TeamMarketLine(line=-3.5, **common)
    db.add_all([row_a, row_b])
    await db.flush()
    assert row_a.observed_at == row_b.observed_at, "test setup requires a genuine tie"

    winner = row_a if row_a.id > row_b.id else row_b
    loser = row_b if winner is row_a else row_a

    kwargs = dict(
        game_id=game.id, market="spread", side="home",
        price_american=-110, source="espn", line_type="live",
    )
    # Matching the tiebreak-selected "latest" row's value must be treated as
    # unchanged (no write); matching the OTHER tied row's value must be
    # treated as a real change (write) - proving the secondary `id` sort key
    # decides which of the two tied rows counts as "latest", not row order
    # as returned by Postgres absent an explicit tiebreak.
    assert await record_team_line(db, line=winner.line, **kwargs) is False
    assert await record_team_line(db, line=loser.line, **kwargs) is True
