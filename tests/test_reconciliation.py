"""src/services/reconciliation.py: source freshness and price divergence.

Freshness deliberately reads ingestion_runs, not rows_written or line-table
recency - record_team_line only writes a row when the value actually
changed (src/ingest/lines.py's own docstring), so a healthy, unchanged
market has rows_written == 0 on every tick. A row-count-based check would
false-alarm on exactly the steady state this is meant to leave alone.
"""

from __future__ import annotations

from datetime import timedelta

from src.ingest.identity import resolve_team
from src.models.base import utcnow
from src.models.facts import Game, TeamMarketLine
from src.models.governance import IngestionRun
from src.services.reconciliation import (
    check_price_divergence,
    check_source_freshness,
)

# -------------------------------------------------------------- freshness --


async def test_a_recently_succeeded_run_raises_no_issue(db):
    db.add(
        IngestionRun(
            source="pinnacle_nfl", status="succeeded",
            started_at=utcnow() - timedelta(minutes=5), finished_at=utcnow() - timedelta(minutes=4),
        )
    )
    await db.flush()

    issues = await check_source_freshness(db)
    assert not any(i.check == "pinnacle_nfl" for i in issues)


async def test_a_failed_run_is_flagged_regardless_of_age(db):
    db.add(
        IngestionRun(
            source="bovada_nfl", status="failed", detail="HTTP 403",
            started_at=utcnow() - timedelta(minutes=1), finished_at=utcnow(),
        )
    )
    await db.flush()

    issues = await check_source_freshness(db)
    matches = [i for i in issues if i.check == "bovada_nfl"]
    assert len(matches) == 1
    assert "HTTP 403" in matches[0].detail


async def test_a_stale_succeeded_run_is_flagged(db):
    """bovada polls every 1800s; 3x that (90 min) with no successful run
    since is stale."""
    db.add(
        IngestionRun(
            source="bovada_nfl", status="succeeded",
            started_at=utcnow() - timedelta(hours=4), finished_at=utcnow() - timedelta(hours=4),
        )
    )
    await db.flush()

    issues = await check_source_freshness(db)
    assert any(i.check == "bovada_nfl" and "no successful run" in i.detail for i in issues)


async def test_a_run_still_in_progress_is_not_flagged(db):
    db.add(
        IngestionRun(
            source="pinnacle_nfl", status="running",
            started_at=utcnow() - timedelta(hours=5), finished_at=None,
        )
    )
    await db.flush()

    issues = await check_source_freshness(db)
    assert not any(i.check == "pinnacle_nfl" for i in issues)


async def test_a_source_that_has_never_run_is_not_flagged(db):
    # No IngestionRun rows at all (conftest truncates before every test) -
    # nothing to compare freshness against yet, e.g. right after a fresh
    # deploy before the first beat tick.
    issues = await check_source_freshness(db)
    assert issues == []


# ------------------------------------------------------------- divergence --


async def _seed_game(db) -> Game:
    home = await resolve_team(db, "Seattle Seahawks", sport="nfl")
    away = await resolve_team(db, "New England Patriots", sport="nfl")
    game = Game(season=2026, week=1, status="scheduled", home_team_id=home.id, away_team_id=away.id)
    db.add(game)
    await db.flush()
    return game


async def test_close_spreads_between_two_sources_raise_no_issue(db):
    game = await _seed_game(db)
    db.add_all([
        TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.5, price_american=-110, source="pinnacle", line_type="live"),
        TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.0, price_american=-115, source="bovada", line_type="live"),
    ])
    await db.flush()

    issues = await check_price_divergence(db, "nfl")
    assert issues == []


async def test_a_large_spread_gap_is_flagged(db):
    """A +3.5/-3.5 mismatch (a sign bug) produces a 7-point gap, far beyond
    any real disagreement between two live books."""
    game = await _seed_game(db)
    db.add_all([
        TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.5, price_american=-110, source="pinnacle", line_type="live"),
        TeamMarketLine(game_id=game.id, market="spread", side="home", line=3.5, price_american=-110, source="bovada", line_type="live"),
    ])
    await db.flush()

    issues = await check_price_divergence(db, "nfl")
    assert len(issues) == 1
    assert issues[0].check == "divergence"
    assert "spread/home" in issues[0].detail


async def test_close_moneylines_raise_no_issue(db):
    game = await _seed_game(db)
    db.add_all([
        TeamMarketLine(game_id=game.id, market="moneyline", side="home", line=None, price_american=-185, source="pinnacle", line_type="live"),
        TeamMarketLine(game_id=game.id, market="moneyline", side="home", line=None, price_american=-175, source="bovada", line_type="live"),
    ])
    await db.flush()

    issues = await check_price_divergence(db, "nfl")
    assert issues == []


async def test_a_large_moneyline_gap_is_flagged(db):
    game = await _seed_game(db)
    db.add_all([
        TeamMarketLine(game_id=game.id, market="moneyline", side="home", line=None, price_american=-500, source="pinnacle", line_type="live"),
        TeamMarketLine(game_id=game.id, market="moneyline", side="home", line=None, price_american=150, source="bovada", line_type="live"),
    ])
    await db.flush()

    issues = await check_price_divergence(db, "nfl")
    assert len(issues) == 1
    assert "moneyline/home" in issues[0].detail


async def test_a_single_source_produces_no_comparison(db):
    game = await _seed_game(db)
    db.add(
        TeamMarketLine(game_id=game.id, market="spread", side="home", line=-3.5, price_american=-110, source="pinnacle", line_type="live")
    )
    await db.flush()

    issues = await check_price_divergence(db, "nfl")
    assert issues == []
