"""Scoped reads must reject stale evidence without rebuilding forecasts."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import pytest
from src.models.facts import Game
from src.models.sleeper import SleeperLeagueSnapshot
from src.models.governance import DerivedCheckpoint
from src.services import fantasy_read_model as legacy, workspace_checkpoints as scoped
from src.services.forecast_evidence import digest
from src.models.identity import Team
from src.models.sleeper import SleeperLeague


@pytest.mark.parametrize('age,expected', [(1,'exact_team'), (7,'unresolved_team'), (-1,'unresolved_team')])
async def test_espn_defense_binding_uses_fresh_stored_provider_team_id(db, monkeypatch, age, expected):
    now = datetime.now(timezone.utc)
    db.add(Team(sport='nfl', espn_id='4', nflverse_abbr='CIN', name='Cincinnati Bengals'))
    db.add(SleeperLeague(league_id='espn:test', platform='espn', sport='nfl', name='Test',
        season='2026', status='in_season', roster_positions=[], settings={}, scoring_settings={},
        synced_at=now-timedelta(hours=age), raw={'defense_identities':[
            {'player_id':'-999','team_id':'4'}]}))
    await db.commit()
    from src.services import fantasy_decision_models
    async def build(*args, **kwargs):
        return {**candidate(), 'players':[{'player_id':'-999','position':'DEF','team':'CIN',
            'identity_status':'unresolved','weekly_evidence':{'source':'espn'}}]}
    monkeypatch.setattr(fantasy_decision_models, 'build', build)
    await legacy.refresh(db, 'espn:test')
    result = await scoped.read(db, 'espn:test')
    assert result['players'][0]['_workspace_team_identity']['status'] == expected


async def test_team_identity_is_bound_with_checkpoint_read_without_changing_forecast(db, monkeypatch):
    team = Team(sport='nfl', espn_id='4', nflverse_abbr='CIN', name='Cincinnati Bengals')
    db.add(team)
    await db.commit()
    from src.services import fantasy_decision_models
    async def build(*args, **kwargs):
        return {**candidate(), 'players':[{'player_id':'CIN','position':'DEF','team':'CIN',
            'identity_status':'unresolved','weekly_evidence':{'source':'sleeper'}}]}
    monkeypatch.setattr(fantasy_decision_models, 'build', build)
    await legacy.refresh(db, 'a')
    result = await scoped.read(db, 'a')
    assert result['players'][0]['_workspace_team_identity'] == {
        'status':'exact_team', 'canonical_team_id':str(team.id)}
    assert result['players'][0]['identity_status'] == 'unresolved'


def candidate():
    return {'status': 'candidate', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'players': [], 'input_timestamps': {}}


async def seed(db, monkeypatch, league='a'):
    from src.services import fantasy_decision_models
    async def build(*args, **kwargs):
        return candidate()
    monkeypatch.setattr(fantasy_decision_models, 'build', build)
    await legacy.refresh(db, league)


async def test_other_league_write_preserves_only_scoped_reader(db, monkeypatch):
    await seed(db, monkeypatch)
    db.add(SleeperLeagueSnapshot(league_id='b', week=4, kind='projections', payload={}))
    await db.commit()
    assert await legacy.read(db, 'a') is None
    result = await scoped.read(db, 'a')
    assert result['read_model']['invalidation_scope'] == 'league_and_shared_nfl'


async def test_own_league_and_shared_writes_invalidate(db, monkeypatch):
    await seed(db, monkeypatch)
    db.add(SleeperLeagueSnapshot(league_id='a', week=4, kind='projections', payload={}))
    await db.commit()
    assert await scoped.read(db, 'a') is None
    await db.rollback()
    await seed(db, monkeypatch)
    db.add(Game(sport='nfl', season=2026, status='scheduled'))
    await db.commit()
    assert await scoped.read(db, 'a') is None


async def test_league_reassignment_invalidates_both_domains(db, monkeypatch):
    row = SleeperLeagueSnapshot(league_id='a', week=4, kind='projections', payload={})
    db.add(row)
    await db.commit()
    await seed(db, monkeypatch, 'a')
    await seed(db, monkeypatch, 'b')
    row.league_id = 'b'
    await db.commit()
    assert await scoped.read(db, 'a') is None
    assert await scoped.read(db, 'b') is None


async def test_rollback_does_not_invalidate_scoped_checkpoint(db, monkeypatch):
    await seed(db, monkeypatch)
    db.add(SleeperLeagueSnapshot(league_id='a', week=4, kind='projections', payload={}))
    await db.flush()
    assert await scoped.read(db, 'a') is None
    await db.rollback()
    assert await scoped.read(db, 'a') is not None


async def test_unbound_checkpoint_uses_conservative_fallback(db, monkeypatch):
    await seed(db, monkeypatch)
    await db.execute(text("DELETE FROM fantasy_checkpoint_scopes WHERE name='fantasy:a'"))
    await db.commit()
    assert (await scoped.read(db, 'a'))['read_model']['invalidation_scope'] == 'legacy_global'
    db.add(SleeperLeagueSnapshot(league_id='b', week=4, kind='projections', payload={}))
    await db.commit()
    assert await scoped.read(db, 'a') is None


async def test_stale_payload_cannot_acquire_fresh_binding(db, monkeypatch):
    await seed(db, monkeypatch)
    checkpoint = await db.get(DerivedCheckpoint, 'fantasy:a')
    original = dict(checkpoint.payload)
    db.add(SleeperLeagueSnapshot(league_id='a', week=4, kind='projections', payload={}))
    await db.commit()
    # Simulate a stale external writer updating cache metadata after sources moved.
    checkpoint.updated_at = datetime.now(timezone.utc)
    await db.commit()
    assert await db.scalar(text("SELECT count(*) FROM fantasy_checkpoint_scopes WHERE name='fantasy:a'")) == 0
    assert checkpoint.payload == original
    assert await scoped.read(db, 'a') is None


async def test_expiry_and_digest_guards_remain(db, monkeypatch):
    await seed(db, monkeypatch)
    checkpoint = await db.get(DerivedCheckpoint, 'fantasy:a')
    checkpoint.digest = '0' * 64
    await db.commit()
    assert await scoped.read(db, 'a') is None
    checkpoint.payload = {**checkpoint.payload, 'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    checkpoint.digest = digest(checkpoint.payload)
    await db.commit()
    assert await scoped.read(db, 'a') is None


async def test_truncation_invalidates_all_leagues(db, monkeypatch):
    await seed(db, monkeypatch, 'a')
    await seed(db, monkeypatch, 'b')
    await db.execute(text('TRUNCATE sleeper_league_snapshots'))
    await db.commit()
    assert await scoped.read(db, 'a') is None
    assert await scoped.read(db, 'b') is None


@pytest.mark.parametrize('changed_league, valid', [('a', False), ('b', True)])
async def test_binding_uses_writer_snapshot_during_concurrent_sync(db, monkeypatch, changed_league, valid):
    from src.services import fantasy_decision_models
    async def build(*args, **kwargs):
        # Source revision was already read inside refresh's repeatable-read
        # transaction. A separate connection now commits new source inputs.
        async with AsyncSession(bind=db.bind) as other:
            other.add(SleeperLeagueSnapshot(league_id=changed_league, week=4,
                                           kind='projections', payload={}))
            await other.commit()
        return candidate()
    monkeypatch.setattr(fantasy_decision_models, 'build', build)
    await legacy.refresh(db, 'a')
    assert await legacy.read(db, 'a') is None
    assert (await scoped.read(db, 'a') is not None) == valid


async def test_pre_migration_epoch_cannot_qualify(db, monkeypatch):
    await seed(db, monkeypatch)
    assert await db.scalar(text("SELECT revision FROM fantasy_scope_revisions WHERE scope='shared'")) > 0
    await db.execute(text("UPDATE fantasy_checkpoint_scopes SET shared_revision=0 WHERE name='fantasy:a'"))
    await db.commit()
    assert await scoped.read(db, 'a') is None


@pytest.mark.parametrize('change', [
    {'generated_at': None}, {'expires_at': 'invalid'},
    {'generated_at': '2026-01-01T00:00:00'}, {'data': None},
])
async def test_malformed_checkpoint_is_withheld_not_server_error(db, monkeypatch, change):
    await seed(db, monkeypatch)
    checkpoint = await db.get(DerivedCheckpoint, 'fantasy:a')
    checkpoint.payload = {**checkpoint.payload, **change}
    checkpoint.digest = digest(checkpoint.payload)
    await db.commit()
    assert await scoped.read(db, 'a') is None
