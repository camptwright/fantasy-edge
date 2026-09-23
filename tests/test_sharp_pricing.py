from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

from src.services.sharp_pricing import comparisons
from src.ingest.theodds import _rows_for


def quotes(market='moneyline', line=None):
    now = datetime.now(timezone.utc)
    game = NS(id=uuid4(), sport='nfl')
    out = []
    for source, prices in [('pinnacle', (-110, -110)), ('theodds_draftkings', (110, -130))]:
        for side, price in zip(('home', 'away'), prices):
            out.append((NS(id=uuid4(), game_id=game.id, source=source, market=market,
                side=side, price_american=price, line=line if side == 'home' or line is None else -line,
                observed_at=now), game))
    return out


def test_sharp_prices_target_not_itself():
    rows = comparisons(quotes())
    assert len(rows) == 2
    assert rows[0]['fair_probability'] == .5
    assert abs(rows[0]['ev_percent'] - 5) < 1e-9
    assert rows[0]['bookmaker'] == 'draftkings'
    assert rows[0]['reference_books'] == ['pinnacle']
    assert not rows[0]['actionable']


def test_reject_different_lines_integer_lines_and_async_quotes():
    rows = quotes('spread', -3.5)
    rows[2][0].line = -4.5
    rows[3][0].line = 4.5
    assert not comparisons(rows)
    assert not comparisons(quotes('spread', -3))
    rows = quotes()
    rows[0][0].observed_at -= timedelta(minutes=6)
    rows[1][0].observed_at -= timedelta(minutes=6)
    assert not comparisons(rows)


def test_same_brand_feeds_not_multiple_votes():
    rows = quotes()
    for line, game in list(rows[:2]):
        rows.append((NS(**{**vars(line), 'id': uuid4(), 'source': 'parlay_pinnacle'}), game))
    assert comparisons(rows)[0]['reference_books'] == ['pinnacle']


def test_parser_keeps_every_named_book():
    markets = [{'key': 'h2h', 'outcomes': [{'name': 'Home', 'price': -110}, {'name': 'Away', 'price': -110}]}]
    event = {'home_team': 'Home', 'away_team': 'Away', 'bookmakers': [
        {'key': 'pinnacle', 'markets': markets}, {'key': 'draftkings', 'markets': markets},
        {'markets': markets}, {'key': 'x'*25, 'markets': markets}]}
    rows = _rows_for(event)
    assert len(rows) == 4
    assert {r['source'] for r in rows} == {'theodds_pinnacle', 'theodds_draftkings'}
