from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from src.ingest.aggregate_props import parse_parlay, parse_sgo, BOOKS, price


def parlay_row(now):
    return {'bookmaker': 'draftkings', 'market_key': 'player_passing_yards',
        'is_dfs_flat_payout': False, 'dfs_normalized': False,
        'commence_time_reported': True, 'player': 'Test Player', 'line': 200.5,
        'over_price': -110, 'under_price': -115, 'last_update': now.isoformat()}


def test_parlay_only_real_prices_and_supported_markets():
    now = datetime.now(timezone.utc)
    good = parlay_row(now)
    assert len(parse_parlay([good], 'nfl', now)) == 1
    for field, value in [('dfs_normalized', True), ('is_dfs_flat_payout', True),
                         ('bookmaker', 'underdog'), ('commence_time_reported', False),
                         ('over_price', None), ('line', float('nan')),
                         ('market_key', 'player_passing_yards_milestones'),
                         ('last_update', (now-timedelta(minutes=16)).isoformat()),
                         ('last_update', (now+timedelta(seconds=1)).isoformat())]:
        assert parse_parlay([{**good, field: value}], 'nfl', now) == []
    for field in ('dfs_normalized', 'is_dfs_flat_payout'):
        absent = deepcopy(good)
        del absent[field]
        assert parse_parlay([absent], 'nfl', now) == []


def test_sgo_matches_both_sides_prices_lines_availability_and_time():
    now = datetime.now(timezone.utc)
    offer = {'available': True, 'odds': '-110', 'overUnder': '200.5', 'lastUpdatedAt': now.isoformat()}
    over = {'statID': 'passing_yards', 'playerID': 'p', 'periodID': 'game', 'betTypeID': 'ou',
            'sideID': 'over', 'opposingOddID': 'u', 'byBookmaker': {'bovada': deepcopy(offer)}}
    under = {**deepcopy(over), 'sideID': 'under'}
    event = {'leagueID': 'NFL', 'status': {'started': False},
             'players': {'p': {'name': 'Test Player'}}, 'odds': {'o': over, 'u': under}}
    payload = {'success': True, 'data': [event]}
    assert len(parse_sgo(payload, 'nfl', now)) == 1
    for field, value in [('available', False), ('overUnder', '201.5'), ('odds', 'bad'),
                         ('lastUpdatedAt', (now-timedelta(hours=1)).isoformat())]:
        changed = deepcopy(payload)
        changed['data'][0]['odds']['u']['byBookmaker']['bovada'][field] = value
        assert parse_sgo(changed, 'nfl', now) == []


def test_initial_book_ownership_prevents_cross_provider_duplicate_offers():
    assert not BOOKS['sgo'] & BOOKS['parlay']
    assert 'fanduel' not in BOOKS['sgo'] | BOOKS['parlay']
    assert price(-99) is None
    assert price('110.5') is None


@pytest.mark.parametrize('sport,raw_stat,expected', [
    ('nfl', 'receiving_receptions', 'receptions'),
    ('ncaaf', 'passing_completions', 'passing_completions'),
    ('mlb', 'batting_hits', 'hits'), ('mlb', 'batting_totalBases', 'total_bases'),
    ('mlb', 'pitching_strikeouts', 'strikeouts'),
    ('nba', 'points', 'points'), ('nba', 'threePointersMade', 'three_pointers_made'),
    ('nba', 'points+rebounds+assists', 'points_rebounds_assists'),
    ('nhl', 'points', 'goals'), ('nhl', 'goals+assists', 'points'),
    ('nhl', 'shots_onGoal', 'shots_on_goal'), ('nhl', 'shots', None),
    ('nhl', 'goalie_saves', 'saves'), ('nhl', 'blocks', 'blocked_shots'),
    ('mlb', 'batting_strikeouts', None), ('mlb', 'strikeouts', None)])
def test_verified_provider_stat_names_preserve_roles(sport, raw_stat, expected):
    now = datetime.now(timezone.utc)
    odds = {}
    for side in ('over', 'under'):
        odds[side] = {'statID': raw_stat, 'playerID': 'p', 'periodID': 'game',
            'betTypeID': 'ou', 'sideID': side, 'opposingOddID': 'under',
            'byBookmaker': {'bovada': {'available': True, 'odds': '-110',
                'overUnder': '1.5', 'lastUpdatedAt': now.isoformat()}}}
    payload = {'success': True, 'data': [{'leagueID': sport.upper(), 'status': {'started': False},
        'players': {'p': {'name': 'Test Player'}}, 'odds': odds}]}
    result = parse_sgo(payload, sport, now)
    assert [r['stat'] for r in result] == ([expected] if expected else [])


async def test_provider_snapshot_time_not_poll_time(db, monkeypatch):
    from src.ingest import aggregate_props as module
    from src.models.facts import Game, QuoteAvailability, PlayerPropLine
    from src.models.identity import Player, Team
    from sqlalchemy import select
    now = datetime.now(timezone.utc)
    home = Team(sport='nfl', name='Fixture Home', nflverse_abbr='FH', espn_id='991')
    away = Team(sport='nfl', name='Fixture Away', nflverse_abbr='FA', espn_id='992')
    db.add_all([home, away])
    await db.flush()
    game = Game(sport='nfl', season=2026, home_team_id=home.id, away_team_id=away.id,
                game_time=now+timedelta(hours=1), status='scheduled')
    player = Player(sport='nfl', full_name='Test Player', current_team_id=home.id)
    db.add_all([game, player])
    await db.flush()
    monkeypatch.setattr(module, '_match_game', AsyncMock(return_value=game))
    updated = now-timedelta(minutes=5)
    row = {**parlay_row(updated), 'commence_time': game.game_time.isoformat()}
    result = await module.ingest(db, 'parlay', 'nfl', [row], now)
    assert result['written'] == 1
    quote = await db.scalar(select(PlayerPropLine))
    seen = await db.get(QuoteAvailability, ('prop', quote.id))
    assert seen.seen_at == updated
    assert seen.event_binding['game_id'] == str(game.id)
    assert seen.event_binding['kickoff'] == game.game_time.isoformat()
    assert quote.observed_at > updated
    repeated = await module.ingest(db, 'parlay', 'nfl', [row], now+timedelta(minutes=1))
    assert repeated['written'] == 0
    assert seen.seen_at == updated


def test_parlay_budget_reserves_calls_for_later_nfl_slots():
    from datetime import datetime, timezone
    from src.ingest.aggregate_props import kickoff_slots, parlay_allowed

    def t(h, m=0):
        return datetime(2026, 10, 11, h, m, tzinfo=timezone.utc)
    # 2026-10-11: London 13:30, main slate 17:00, late games 20:05 and 20:25 (one slot).
    slots = kickoff_slots([t(13, 30), t(17), t(17), t(20, 5), t(20, 25)])
    assert slots == [t(13, 30), t(17), t(20, 5)]
    # London window: at most three calls while later slots still need one each.
    assert parlay_allowed('nfl', t(11, 35), slots, {}, 8)
    assert not parlay_allowed('nfl', t(13, 0), slots, {t(13, 30).isoformat(): 3}, 5)
    # Main slate: may spend down to the late slot's reserved call, not past it.
    assert parlay_allowed('nfl', t(16, 30), slots, {t(13, 30).isoformat(): 3}, 2)
    assert not parlay_allowed('nfl', t(16, 30), slots, {t(13, 30).isoformat(): 3}, 1)
    assert parlay_allowed('nfl', t(19, 30), slots, {}, 1)  # the last slot may use the last call
    assert not parlay_allowed('nfl', t(14, 30), slots, {}, 8)  # nothing kicking off within 2 hours
    # Other sports only use calls that no NFL slot is waiting for.
    assert not parlay_allowed('mlb', t(11), slots, {}, 3)
    assert parlay_allowed('mlb', t(11), slots, {}, 4)
    assert parlay_allowed('mlb', t(22), [], {}, 1) and not parlay_allowed('mlb', t(22), [], {}, 0)


async def test_paid_payload_is_ingested_even_when_the_raw_archive_fails(db, monkeypatch):
    import src.ingest.aggregate_props as ap
    import src.scheduler.calibration as calibration
    calls = []

    async def fake_ingest(db, provider, sport, payload, now):
        calls.append(sport)
        return {'parsed': 1, 'written': 1, 'parked': 0, 'parked_reasons': {}}

    def full_disk(kind, payload):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(ap, 'ingest', fake_ingest)
    monkeypatch.setattr(calibration, 'archive', full_disk)
    result = await ap.ingest_then_archive(db, 'parlay', 'nfl', [])
    assert calls == ['nfl'] and result['written'] == 1 and result['archive_error'].startswith('OSError')
