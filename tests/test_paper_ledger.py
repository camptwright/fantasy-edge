from datetime import timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, text
from src.models.base import utcnow
from src.models.facts import Game, TeamMarketLine, QuoteAvailability
from src.models.ledger import LedgerBet
from src.services.paper_ledger import capture


async def test_paper_capture_first_qualified_contract_only(db):
    await db.execute(text('DELETE FROM ledger_policies'))
    game = Game(sport='nfl', season=2026, status='scheduled', game_time=utcnow()+timedelta(hours=2))
    db.add(game); await db.flush()
    quote = TeamMarketLine(game_id=game.id, source='testbook', market='moneyline', side='home',
        price_american=110, line_type='live', observed_at=utcnow())
    db.add(quote); await db.flush()
    db.add(QuoteAvailability(kind='team', quote_id=quote.id, source='testbook', available=True, seen_at=utcnow()))
    await db.flush()
    row = dict(id=str(quote.id), side='home', actionable=False, model_version='test-v1')
    with patch('src.api.routers.sportsbook.signal_rows', AsyncMock(return_value=[row])), \
         patch('src.api.routers.sportsbook.prop_rows', AsyncMock(return_value=[])):
        assert (await capture(db))['captured'] == 0
        row['actionable'] = True
        assert (await capture(db))['captured'] == 1
        assert (await capture(db))['duplicates'] == 1
        bet = await db.scalar(select(LedgerBet).where(LedgerBet.game_id == game.id))
        assert bet.mode == 'paper' and float(bet.stake) == 1
        assert bet.terms['prediction_evidence']['model_version'] == 'test-v1'
        # Withdrawal cannot be recorded in a new model cohort.
        row['model_version'] = 'test-v2'
        game.game_time = utcnow()-timedelta(seconds=1)
        await db.flush()
        assert (await capture(db))['rejected'] == 1
