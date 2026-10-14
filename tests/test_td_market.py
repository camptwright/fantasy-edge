from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from src.ingest.aggregate_props import parse_parlay
from src.services import td_market


def row(now, **kw):
    return {'bookmaker': 'draftkings', 'market_key': 'player_anytime_td', 'period': 'FULL', 'line': 0.5,
            'is_dfs_flat_payout': False, 'dfs_normalized': False, 'commence_time_reported': True,
            'player': 'Bo Nix', 'over_price': 406, 'under_price': None, 'home_team': 'Denver Broncos',
            'away_team': 'Seattle Seahawks', 'commence_time': (now + timedelta(days=2)).isoformat(),
            'last_update': now.isoformat(), **kw}


def test_yes_only_rows_are_research_prices_never_offers():
    now = datetime.now(timezone.utc)
    assert parse_parlay([row(now)], 'nfl', now) == []          # stays out of player_prop_lines
    assert [r['no'] for r in td_market.extract([row(now), row(now, under_price=-610)])] == [None, -610]
    for bad in ({'dfs_normalized': True}, {'bookmaker': 'underdog'}, {'line': 1.5}, {'over_price': None},
                {'period': '1H'}, {'market_key': 'player_first_td'}, {'commence_time_reported': False}):
        assert td_market.extract([row(now, **bad)]) == []
    assert round(td_market.implied(406), 4) == 0.1976 and td_market.implied(-610) > 0.85


def test_parlay_pass_tds_are_priced_offers():
    now = datetime.now(timezone.utc)
    pass_td = {**row(now), 'market_key': 'player_pass_tds', 'line': 1.5, 'over_price': -150, 'under_price': 120}
    assert [r['stat'] for r in parse_parlay([pass_td], 'nfl', now)] == ['passing_touchdowns']


async def test_capture_freezes_matched_pre_kickoff_quotes(db, tmp_path, monkeypatch):
    import src.ingest.prop_events as prop_events
    import src.ingest.theodds_props as theodds_props
    now = datetime.now(timezone.utc)
    game = SimpleNamespace(id=uuid.uuid4(), status='scheduled', game_time=now + timedelta(days=2), season=2026, week=6)
    player = SimpleNamespace(id=uuid.uuid4())

    async def match(db, event, sport):
        return game if event['home_team'] == 'Denver Broncos' else None

    monkeypatch.setattr(prop_events, 'match_priced_event', match)
    monkeypatch.setattr(theodds_props, 'select_player', lambda players, name, g: player if name == 'Bo Nix' else None)
    monkeypatch.setattr(td_market, 'archive_root', lambda: tmp_path)
    payload = [row(now), row(now, bookmaker='pinnacle', under_price=-610), row(now, player='Nobody'),
               row(now, home_team='Elsewhere')]
    result = await td_market.capture(db, 'nfl', payload, now)
    assert result == {'td_rows': 4, 'td_captured': 2, 'td_unmatched': 2}
    assert (await td_market.capture(db, 'nfl', payload, now))['td_captured'] == 0   # create-only
    later = now + timedelta(minutes=30)
    await td_market.capture(db, 'nfl', [row(now, over_price=380, last_update=later.isoformat())], later)
    frozen = td_market.frozen(tmp_path)
    assert {k[2]: v['yes'] for k, v in frozen.items()} == {'draftkings': 380, 'pinnacle': 406}
