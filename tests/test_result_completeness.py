from datetime import datetime, timedelta, timezone
from src.models.facts import Game, PlayerPropLine, PlayerGameStat
from src.models.identity import Player
from src.services.result_completeness import status


async def test_quote_scope_distinguishes_missing_field_and_unknown_participation(db):
    now = datetime.now(timezone.utc)
    g = Game(sport='mlb', season=2026, status='final', game_time=now-timedelta(days=1))
    a, b = Player(sport='mlb', full_name='Played'), Player(sport='mlb', full_name='Unknown')
    db.add_all([g, a, b])
    await db.flush()
    for p in (a, b):
        db.add(PlayerPropLine(player_id=p.id, game_id=g.id, stat_type='hits', line=.5,
                             source='test', observed_at=now))
    db.add(PlayerGameStat(player_id=a.id, game_id=g.id, stat_type='runs', value=0))
    await db.flush()
    report = await status(db)
    assert report['expected_outcomes'] == 2
    assert {r['status'] for r in report['counts']} == {'missing_stat', 'participation_unconfirmed'}
    db.add(PlayerGameStat(player_id=a.id, game_id=g.id, stat_type='hits', value=0))
    await db.flush()
    assert {r['status'] for r in (await status(db))['counts']} == {'present', 'participation_unconfirmed'}
    assert (await status(db, sport='nfl'))['expected_outcomes'] == 0
    assert (await status(db, sport='mlb', offset=5000))['expected_outcomes'] == 0
