from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
from sqlalchemy import select

from src.ingest.result_repair import observe, reconcile, sync_results
from src.models.facts import Game, PlayerGameStat
from src.models.governance import IngestionRun, ResultCorrection, ResultSyncState
from src.models.identity import Player, PlayerExternalId
from src.services.forecast_grading import outcome


@pytest.fixture(autouse=True)
def isolated_evidence_archive(tmp_path, monkeypatch):
    monkeypatch.setattr('src.scheduler.calibration.get_settings',
                        lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))


def test_correction_needs_separated_confirmation_and_retains_old_value():
    now = datetime.now(timezone.utc)
    fact = SimpleNamespace(id=uuid.uuid4(), value=2)
    proposal, applied = observe(fact, None, 3, 'mlb_stats_api', '123', 'a'*64, now)
    assert fact.value == 2 and not applied and proposal.status == 'pending'
    _, applied = observe(fact, proposal, 3, 'mlb_stats_api', '123', 'b'*64, now+timedelta(minutes=29))
    assert fact.value == 2 and not applied
    _, applied = observe(fact, proposal, 3, 'mlb_stats_api', '123', 'b'*64, now+timedelta(minutes=31))
    assert applied and fact.value == 3 and proposal.old_value == 2 and proposal.status == 'applied'


@pytest.mark.parametrize('new', [2, 4])
def test_reversion_or_changed_proposal_resets_confirmation(new):
    now = datetime.now(timezone.utc)
    fact = SimpleNamespace(id=uuid.uuid4(), value=2)
    old, _ = observe(fact, None, 3, 'p', '1', 'a'*64, now)
    fresh, applied = observe(fact, old, new, 'p', '1', 'b'*64, now+timedelta(hours=1))
    assert old.status == 'superseded' and not applied and fact.value == 2
    assert fresh is None if new == 2 else fresh.first_seen_at == now+timedelta(hours=1)


async def seed(db, event='123', days=1):
    game = Game(sport='mlb', season=2026, status='final', mlb_game_pk=event,
                game_time=datetime.now(timezone.utc)-timedelta(days=days))
    player = Player(sport='mlb', full_name='Fixture Player')
    db.add_all([game, player])
    await db.flush()
    db.add(PlayerExternalId(source='mlb_stats_api', external_id=event, player_id=player.id))
    await db.commit()
    return game, player


async def make_due(db, game):
    state = await db.get(ResultSyncState, (game.id, 'mlb_stats_api'))
    state.next_attempt_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    await db.commit()


async def test_retry_unmapped_delayed_fields_and_old_success_marker(db):
    game, player = await seed(db)
    db.add(IngestionRun(source='mlb_box_123', status='succeeded'))
    await db.commit()
    parsed = {'123': {'hits': 2}, '999': {'hits': 1}}
    fetch = AsyncMock(return_value=({'verified': True}, parsed))
    result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    assert result['rows_written'] == 1 and result['unmapped_players'] == 1
    assert (await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch))['games'] == 0
    second = Player(sport='mlb', full_name='Later Identity')
    db.add(second)
    await db.flush()
    db.add(PlayerExternalId(source='mlb_stats_api', external_id='999', player_id=second.id))
    parsed['123']['runs'] = 0
    await make_due(db, game)
    result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    assert result['rows_written'] == 2 and result['unmapped_players'] == 0
    facts = (await db.scalars(select(PlayerGameStat))).all()
    assert len(facts) == 3
    assert not any(f.stat_type == 'rbis' for f in facts)


async def test_failed_game_does_not_starve_later_game(db):
    bad, _ = await seed(db, '1')
    good, _ = await seed(db, '2', days=30)
    async def fetch(client, event):
        if event == '1':
            raise httpx.ReadTimeout('test')
        return {'verified': True}, {event: {'hits': 2}}
    result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch, limit=2)
    assert result['games'] == 2 and result['deferred'] == 1 and result['rows_written'] == 1
    state = await db.get(ResultSyncState, (bad.id, 'mlb_stats_api'))
    assert state.status == 'deferred' and state.next_attempt_at > state.last_attempt_at


async def test_applied_correction_regrades_without_changing_forecast(db):
    game, player = await seed(db)
    fetch = AsyncMock(return_value=({}, {'123': {'hits': 2}}))
    await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    fetch.return_value = ({}, {'123': {'hits': 3}})
    await make_due(db, game)
    result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    assert result['corrections_pending'] == 1 and result['corrections_applied'] == 0
    correction = await db.scalar(select(ResultCorrection))
    fact = await db.scalar(select(PlayerGameStat))
    record = dict(kind='player', player_id=str(player.id), game_id=str(game.id), market='hits', line=2.5)
    key = (str(player.id), str(game.id), 'hits')
    assert outcome(record, game, {key: fact.value}, game.game_time-timedelta(hours=1)) == ('graded', 0)
    assert outcome(record, game, {key: fact.value}, game.game_time-timedelta(hours=1), {key}) == ('needs_review', None)
    correction.first_seen_at -= timedelta(hours=1)
    await make_due(db, game)
    result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    assert result['corrections_applied'] == 1
    assert correction.status == 'applied' and correction.old_value == 2 and correction.new_value == 3
    assert outcome(record, game, {key: fact.value}, game.game_time-timedelta(hours=1)) == ('graded', 1)
    assert record['line'] == 2.5
    from src.services.result_repair_status import status
    report = await status(db)
    assert report['correction_counts'] == {'applied': 1}
    assert report['recent_corrections'][0]['old_value'] == 2


async def test_savepoint_rolls_back_partial_observation(db, monkeypatch):
    game, player = await seed(db)
    original = reconcile
    async def broken(*args, **kwargs):
        await original(*args, **kwargs)
        raise ValueError('injected after fact insert')
    monkeypatch.setattr('src.ingest.result_repair.reconcile', broken)
    fetch = AsyncMock(return_value=({}, {'123': {'hits': 2}}))
    assert (await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch))['deferred'] == 1
    assert (await db.scalars(select(PlayerGameStat))).all() == []
    assert (await db.scalars(select(ResultCorrection))).all() == []


async def test_unknown_time_deferred_without_http(db):
    game, _ = await seed(db)
    game.game_time = None
    await db.commit()
    fetch = AsyncMock()
    assert (await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch))['deferred'] == 1
    fetch.assert_not_called()


async def test_explicit_refresh_keeps_confirmation_delay(db):
    game, _ = await seed(db)
    fetch = AsyncMock(return_value=({}, {'123': {'hits': 2}}))
    await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch)
    fetch.return_value = ({}, {'123': {'hits': 3}})
    for _ in range(2):
        result = await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch,
                                    game_ids=[game.id], refresh=True)
        assert result['corrections_pending'] == 1 and result['corrections_applied'] == 0
    assert (await db.scalar(select(PlayerGameStat))).value == 2
    with pytest.raises(ValueError):
        await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch, refresh=True)
