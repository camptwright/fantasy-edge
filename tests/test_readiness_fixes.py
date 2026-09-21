from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from src.models.facts import Game, PlayerPropLine, PlayerGameStat
from src.models.identity import Player
from src.models.ratings import TeamRating
from src.ingest.identity import resolve_team
from src.ingest.lines import record_prop_line
from src.ingest.mlb import sync_schedule
from src.services.quote_eligibility import confirm_quote, exclusion, withdraw_absent_props
from src.api.routers.sportsbook import prop_rows, props_best, build_parlay, ParlayBuildRequest
from src.api.routers.sportsbook import recommendations
from src.models.governance import RecommendationSnapshot


async def offer(db, *, status='scheduled', timed=True, linked=True, source='test'):
    now = datetime.now(timezone.utc)
    player = Player(sport='ncaaf', full_name='Eligibility Player')
    game = Game(sport='ncaaf', season=2026, status=status,
                game_time=now+timedelta(days=1) if timed else None)
    db.add_all([player, game])
    await db.flush()
    for value in (1., 2., 3., 4.):
        past = Game(sport='ncaaf', season=2025, status='final', game_time=now-timedelta(days=30+value))
        db.add(past)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=past.id, stat_type='receptions', value=value))
    quote = PlayerPropLine(player_id=player.id, game_id=game.id if linked else None, source=source,
        stat_type='receptions', line=2.5, over_price_american=-110, under_price_american=-110, observed_at=now)
    db.add(quote)
    await db.flush()
    await confirm_quote(db, 'prop', quote)
    await db.commit()
    return game, quote


@pytest.mark.parametrize('status,timed,linked,reason', [
    ('final', True, True, 'event_not_pregame'), ('in_progress', True, True, 'event_not_pregame'),
    ('scheduled', False, True, 'unknown_start_time'), ('scheduled', True, False, 'unlinked_event')])
async def test_ineligible_props_never_rank_or_receive_override(db, status, timed, linked, reason):
    await offer(db, status=status, timed=timed, linked=linked)
    row = (await prop_rows(db, 'ncaaf'))[0]
    assert row['exclusion_reason'] == reason and not row['actionable']
    assert row['edge_percent'] is None and row['calibration_candidate_id'] is None
    assert (await props_best('ncaaf', db))['items'] == []


async def test_unchanged_offer_refreshes_metadata_not_history(db):
    game, quote = await offer(db)
    original_time = quote.observed_at
    assert not await record_prop_line(db, player_id=quote.player_id, game_id=game.id,
        stat_type=quote.stat_type, line=quote.line, over_price_american=-110, under_price_american=-110, source=quote.source)
    assert await db.scalar(select(func.count()).select_from(PlayerPropLine)) == 1
    assert quote.observed_at == original_time
    assert (await prop_rows(db, 'ncaaf'))[0]['actionable']
    await withdraw_absent_props(db, quote.source, datetime.now(timezone.utc)+timedelta(seconds=1))
    await db.commit()
    row = (await prop_rows(db, 'ncaaf'))[0]
    assert row['exclusion_reason'] == 'offer_withdrawn' and row['edge_percent'] is None


def test_stale_future_and_missing_confirmation_fail_closed():
    now = datetime.now(timezone.utc)
    game = SimpleNamespace(status='scheduled', game_time=now+timedelta(hours=1))
    quote = SimpleNamespace(observed_at=now-timedelta(days=2))
    assert exclusion(game, quote, None, now) == 'availability_unverified'
    assert exclusion(game, quote, SimpleNamespace(available=True, seen_at=now-timedelta(hours=1)), now) == 'offer_stale'
    assert exclusion(game, quote, SimpleNamespace(available=True, seen_at=now), now) is None
    game.game_time = now
    assert exclusion(game, quote, SimpleNamespace(available=True, seen_at=now), now) == 'event_not_pregame'


@pytest.mark.parametrize('side', ['over', 'under'])
async def test_parlay_rejects_duplicate_and_opposite_legs(db, side):
    _, quote = await offer(db)
    request = ParlayBuildRequest(legs=[{'kind': 'prop', 'id': quote.id, 'side': 'over'},
                                     {'kind': 'prop', 'id': quote.id, 'side': side}])
    with pytest.raises(HTTPException) as err:
        await build_parlay(request, db)
    assert err.value.status_code == 422


async def test_latest_props_keep_separate_events(db):
    _, quote = await offer(db)
    game = Game(sport='ncaaf', season=2026, status='scheduled', game_time=datetime.now(timezone.utc)+timedelta(days=7))
    db.add(game)
    await db.flush()
    await record_prop_line(db, player_id=quote.player_id, game_id=game.id, stat_type=quote.stat_type,
        line=3.5, over_price_american=-110, under_price_american=-110, source=quote.source)
    await db.commit()
    assert len(await prop_rows(db, 'ncaaf')) == 2


async def test_cached_narrative_is_withheld_when_event_starts(db):
    from src.services.recommendations import generate_narrative
    game, quote = await offer(db)
    quote.line = .5  # Positive-EV quote, not the original 50/50 line at -110.
    await db.commit()
    content = await generate_narrative(db, with_evidence=True)
    assert content['quote_ids'] == [str(quote.id)]
    db.add(RecommendationSnapshot(**content))
    await db.commit()
    assert (await recommendations(db))['narrative'] == content['narrative']
    game.status = 'in_progress'
    await db.commit()
    assert (await recommendations(db))['narrative'] is None


async def test_mlb_reconciles_overdue_and_updates_ratings_only_once(db, monkeypatch):
    now = datetime.now(timezone.utc)
    home = await resolve_team(db, 'New York Yankees', sport='mlb')
    away = await resolve_team(db, 'Boston Red Sox', sport='mlb')
    db.add(Game(sport='mlb', season=2026, status='in_progress', mlb_game_pk='123',
        home_team_id=home.id, away_team_id=away.id, game_time=now-timedelta(days=5)))
    await db.commit()
    payload = {'dates': [{'games': [{'gamePk': 123, 'season': '2026', 'gameType': 'R',
        'gameDate': (now-timedelta(days=5)).isoformat(), 'status': {'abstractGameState': 'Final'},
        'teams': {'home': {'team': {'name': home.name}, 'score': 5},
                  'away': {'team': {'name': away.name}, 'score': 3}}}]}]}
    calls = []
    async def get(self, url, **kwargs):
        params = kwargs['params']
        calls.append(params)
        data = payload if 'gamePks' in params else {'dates': []}
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    await sync_schedule(db)
    assert calls[0]['startDate'] == (now.date()-timedelta(days=3)).isoformat()
    assert calls[1]['gamePks'] == '123'
    assert (await db.scalar(select(Game))).status == 'final'
    before = [(r.team_id, r.rating, r.games_played) for r in (await db.scalars(select(TeamRating))).all()]
    await sync_schedule(db)
    assert before == [(r.team_id, r.rating, r.games_played) for r in (await db.scalars(select(TeamRating))).all()]
