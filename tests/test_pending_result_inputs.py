from datetime import datetime, timedelta, timezone
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.models.governance import ResultCorrection
from src.services.projections import project_stats
from src.services.player_features import snapshots


async def test_pending_game_excluded_from_projection_and_shadow_then_restored(db):
    now = datetime.now(timezone.utc)
    player = Player(sport='mlb', full_name='Correction Fixture')
    db.add(player)
    await db.flush()
    facts = []
    for i in range(4):
        game = Game(sport='mlb', season=2026, status='final', game_time=now-timedelta(days=i+1))
        db.add(game)
        await db.flush()
        fact = PlayerGameStat(player_id=player.id, game_id=game.id, stat_type='hits', value=i)
        db.add(fact)
        facts.append(fact)
    await db.flush()
    key = (player.id, 'hits')
    prop = {'id': 'quote', 'player_id': str(player.id), 'stat_type': 'hits'}
    assert key in await project_stats(db, {key})
    assert 'quote' in await snapshots(db, [prop], now)
    # A different stat pending on the same player-game also blocks that game.
    disputed = PlayerGameStat(player_id=player.id, game_id=facts[0].game_id, stat_type='runs', value=0)
    db.add(disputed)
    await db.flush()
    correction = ResultCorrection(stat_id=disputed.id, provider='mlb_stats_api', event_id='1',
        old_value=0, new_value=1, first_seen_at=now, last_seen_at=now,
        first_payload_hash='a'*64, last_payload_hash='b'*64, status='pending')
    db.add(correction)
    await db.flush()
    assert await project_stats(db, {key}) == {}
    assert await snapshots(db, [prop], now) == {}
    correction.status = 'applied'
    disputed.value = 1
    await db.flush()
    assert key in await project_stats(db, {key})
    assert 'quote' in await snapshots(db, [prop], now)
