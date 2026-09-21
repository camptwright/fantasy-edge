from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import update

from src.api.routers import sportsbook
from src.models.facts import Game, PlayerGameStat, PlayerPropLine, QuoteAvailability
from src.models.identity import Player
from src.models.governance import RecommendationSnapshot
from src.services.projections import project_stats, _project_stats_batch
from src.services.quote_eligibility import confirm_quote


async def test_backtest_batches_preserve_chronological_candidate_split(monkeypatch):
    from types import SimpleNamespace
    from src.services import prop_backtest
    from src.services.backtest import BacktestPrediction
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(all=lambda: list(range(25)))
    early = BacktestPrediction(uuid.uuid4(), 'passing_yards', .4, 0)
    late = BacktestPrediction(uuid.uuid4(), 'passing_yards', .6, 1)
    async def batch(db, sport, players, chronology):
        row = late if players[0] == 0 else early
        chronology[id(row)] = 2 if row is late else 1
        return {'passing_yards': [row]}, {'push': 1}
    monkeypatch.setattr(prop_backtest, '_run_prop_batch', batch)
    rows, counts = await prop_backtest.run_prop_backtest(db, 'nfl')
    assert rows['passing_yards'] == [early, late]
    assert counts == {'push': 2}


async def fixture(db, sport='nfl'):
    now = datetime.now(timezone.utc)
    stat_type = 'hits' if sport == 'mlb' else 'passing_yards'
    player = Player(sport=sport, full_name='Performance Fixture')
    game = Game(sport=sport, season=2026, status='scheduled', game_time=now+timedelta(hours=3))
    db.add_all([player, game])
    await db.flush()
    for i in range(5):
        past = Game(sport=sport, season=2026, status='final', game_type='REG', game_time=now-timedelta(days=i+1))
        db.add(past)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id,game_id=past.id,stat_type=stat_type,value=(i % 3 if sport == 'mlb' else 100+i*10)))
    quote = PlayerPropLine(player_id=player.id,game_id=game.id,stat_type=stat_type,source='test',
        line=(.5 if sport == 'mlb' else 125.5),over_price_american=-110,under_price_american=-110,observed_at=now)
    db.add(quote)
    await db.flush()
    await confirm_quote(db,'prop',quote)
    return player,game,quote


@pytest.mark.parametrize('sport', ['nfl', 'ncaaf', 'mlb'])
async def test_populated_slate_crosses_player_batches_and_pages(db, sport, monkeypatch):
    # This exercises paging, not the separately tested approval policy.
    monkeypatch.setattr('src.services.prop_validation.assess', lambda *args: [])
    for _ in range(30):
        await fixture(db, sport)
    legacy = [row for row in await sportsbook.prop_rows(db, sport) if row['actionable']]
    assert len(legacy) == 30
    first = await sportsbook.live_props(sport, 20, 0, db)
    second = await sportsbook.live_props(sport, 20, 20, db)
    assert len(first) == 20 and len(second) == 10
    assert len({row['id'] for row in first+second}) == 30
    expected = {row['id']: row for row in legacy}
    for row in first+second:
        for field in ('model_probability', 'under_model_probability', 'edge_percent', 'under_edge_percent'):
            assert row[field] == expected[row['id']][field]


def test_validation_rejects_invalid_nonempty_offers():
    from scripts.validate_active_slate import validate_rows
    assert validate_rows([{'id': 'a', 'actionable': True, 'model_probability': .5}], 'props') == []
    assert 'invalid_probability' in validate_rows([{'id': 'a', 'actionable': True, 'model_probability': float('nan')}], 'props')
    assert 'ineligible_live_prop' in validate_rows([{'id': 'a', 'actionable': False}], 'props')


async def test_live_matches_legacy_and_projection_batch(db, monkeypatch):
    monkeypatch.setattr('src.services.prop_validation.assess', lambda *args: [])
    player,_,quote = await fixture(db)
    legacy = await sportsbook.prop_rows(db,'nfl')
    live = await sportsbook.prop_rows(db,'nfl',live_only=True)
    assert live == legacy
    keys={(player.id,'passing_yards')}
    assert await project_stats(db,keys) == await _project_stats_batch(db,keys)
    compact = await sportsbook.live_props('nfl',200,0,db)
    assert compact[0]['id'] == str(quote.id)
    assert 'reports' not in compact[0]['injury_context']


async def test_old_quote_cannot_resurrect_after_withdrawn_replacement(db):
    player,game,old = await fixture(db)
    newest = PlayerPropLine(player_id=player.id,game_id=game.id,stat_type=old.stat_type,source=old.source,
        line=130.5,over_price_american=-110,under_price_american=-110,observed_at=old.observed_at+timedelta(microseconds=1))
    db.add(newest)
    await db.flush()
    await confirm_quote(db,'prop',newest)
    await db.execute(update(QuoteAvailability).where(QuoteAvailability.quote_id==newest.id).values(available=False))
    assert await sportsbook.prop_rows(db,'nfl',live_only=True) == []
    assert await sportsbook.prop_rows(db,'nfl',live_only=True,quote_ids={old.id}) == []


@pytest.mark.parametrize('reason',['stale','future_seen','unpriced','started','unlinked','unknown_time'])
async def test_ineligible_quotes_do_not_project(db,monkeypatch,reason):
    _,game,quote = await fixture(db)
    if reason=='stale':
        await db.execute(update(QuoteAvailability).values(seen_at=datetime.now(timezone.utc)-timedelta(hours=1)))
    elif reason=='future_seen':
        await db.execute(update(QuoteAvailability).values(seen_at=datetime.now(timezone.utc)+timedelta(hours=1)))
    elif reason=='unpriced':
        quote.over_price_american=quote.under_price_american=None
    elif reason=='started':
        game.game_time=datetime.now(timezone.utc)-timedelta(minutes=1)
    elif reason=='unlinked':
        quote.game_id=None
    else:
        game.game_time=None
    await db.flush()
    projected=AsyncMock()
    monkeypatch.setattr(sportsbook,'project_stats',projected)
    assert await sportsbook.prop_rows(db,'nfl',live_only=True) == []
    projected.assert_not_awaited()


async def test_narrative_scopes_quotes(db,monkeypatch):
    from src.services import recommendations as service
    quote_id=str(uuid.uuid4())
    row=dict(id=quote_id, actionable=True, line=5.5, model_probability=.7,
             over_price_american=-110)
    text=service.NARRATIVE_VERSION+'\n\n'+service.quote_summary(row,'prop')['text']
    snapshot=RecommendationSnapshot(narrative=text,generated_at=datetime.now(timezone.utc),quote_ids=[quote_id])
    db.add(snapshot)
    await db.flush()
    signals=AsyncMock(return_value=[])
    props=AsyncMock(return_value=[row])
    monkeypatch.setattr(service,'signal_rows',signals)
    monkeypatch.setattr(service,'prop_rows',props)
    assert (await sportsbook.recommendations(db))['narrative']==text
    props.assert_awaited_once_with(db,None,live_only=True,quote_ids={uuid.UUID(quote_id)})
    signals.assert_awaited_once_with(db,None,quote_ids={uuid.UUID(quote_id)})
