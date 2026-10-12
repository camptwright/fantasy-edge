"""Real-Postgres regression tests for changed-row/sport invalidation."""
from sqlalchemy import text
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, PlayerExternalId
from src.models.governance import ResultCorrection
from src.models.base import utcnow
from src.services.fantasy_read_model import revision
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster
from datetime import timedelta


async def test_empty_and_identical_updates_preserve_revision(db):
    game = Game(sport='nfl', season=2026, status='scheduled')
    db.add(game)
    await db.flush()
    before = await revision(db)
    await db.execute(text('UPDATE games SET status=status WHERE false'))
    await db.execute(text('UPDATE games SET status=status'))
    await db.execute(text('DELETE FROM games WHERE false'))
    assert await revision(db) == before
    game.status = 'final'
    await db.flush()
    assert await revision(db) > before


async def test_other_sport_and_sport_reassignment(db):
    before = await revision(db)
    game = Game(sport='mlb', season=2026, status='scheduled')
    db.add(game)
    await db.flush()
    game.status = 'final'
    await db.flush()
    assert await revision(db) == before
    game.sport = 'nfl'
    await db.flush()
    nfl = await revision(db)
    assert nfl > before
    game.sport = 'mlb'
    await db.flush()
    assert await revision(db) > nfl


async def test_stats_and_pending_corrections_follow_game_sport(db):
    player = Player(sport='mlb', full_name='Test player')
    game = Game(sport='mlb', season=2026, status='final')
    db.add_all([player, game])
    await db.flush()
    before = await revision(db)
    stat = PlayerGameStat(player_id=player.id, game_id=game.id, stat_type='hits', value=1)
    db.add(stat)
    await db.flush()
    correction = ResultCorrection(stat_id=stat.id, provider='test', event_id='test',
        old_value=1, new_value=2, first_seen_at=utcnow(), last_seen_at=utcnow(),
        first_payload_hash='a', last_payload_hash='b', status='pending')
    db.add(correction)
    await db.flush()
    assert await revision(db) == before
    game.sport = 'nfl'
    await db.flush()
    before = await revision(db)
    correction.status = 'applied'
    stat.value = 2
    await db.flush()
    assert await revision(db) >= before + 2


async def test_identity_rebinding_invalidates_old_and_new_sports(db):
    nfl = Player(sport='nfl', full_name='NFL test')
    mlb = Player(sport='mlb', full_name='MLB test')
    db.add_all([nfl, mlb])
    await db.flush()
    before = await revision(db)
    crosswalk = PlayerExternalId(player_id=mlb.id, source='test', external_id='test')
    db.add(crosswalk)
    await db.flush()
    assert await revision(db) == before
    crosswalk.player_id = nfl.id
    await db.flush()
    before = await revision(db)
    crosswalk.player_id = mlb.id
    await db.flush()
    assert await revision(db) > before


async def test_truncate_always_invalidates(db):
    before = await revision(db)
    await db.execute(text('TRUNCATE sleeper_league_snapshots'))
    assert await revision(db) > before


async def test_league_json_and_freshness_changes_invalidate(db):
    league = SleeperLeague(league_id='nfl-test', sport='nfl', name='test', season='2026',
        status='in_season', roster_positions=['QB'], settings={}, scoring_settings={}, raw={})
    db.add(league)
    await db.flush()
    snapshot = SleeperLeagueSnapshot(league_id=league.league_id, week=4, kind='projections', payload={'a': 1})
    roster = SleeperRoster(league_id=league.league_id, roster_id=1, starters=[], players=[], settings={})
    db.add_all([snapshot, roster])
    await db.flush()
    before = await revision(db)
    snapshot.payload = {'a': 2}
    roster.synced_at = roster.synced_at + timedelta(seconds=1)
    await db.flush()
    assert await revision(db) >= before + 2
    before = await revision(db)
    await db.delete(snapshot)
    await db.flush()
    assert await revision(db) > before


async def test_other_league_sport_skips_but_orphans_fail_closed(db):
    league = SleeperLeague(league_id='nba-test', sport='nba', name='test', season='2026',
        status='in_season', roster_positions=[], settings={}, scoring_settings={}, raw={})
    before = await revision(db)
    db.add(league)
    await db.flush()
    snapshot = SleeperLeagueSnapshot(league_id=league.league_id, week=4, kind='projections', payload={})
    db.add(snapshot)
    await db.flush()
    assert await revision(db) == before
    snapshot.league_id = 'missing-league'
    await db.flush()
    assert await revision(db) > before


async def test_upsert_with_unchanged_values_does_not_invalidate(db):
    from sqlalchemy.dialects.postgresql import insert
    player = Player(sport='nfl', full_name='test')
    game = Game(sport='nfl', season=2026, status='final')
    db.add_all([player, game])
    await db.flush()
    values = dict(player_id=player.id, game_id=game.id, stat_type='passing_yards', value=100)
    statement = insert(PlayerGameStat).values(**values)
    statement = statement.on_conflict_do_update(constraint='uq_player_game_stat', set_={'value': statement.excluded.value})
    await db.execute(statement)
    before = await revision(db)
    await db.execute(statement)
    assert await revision(db) == before
