from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from src.ingest.underdog import ingest_props


async def test_provider_upgrade_is_audited_without_touching_offer_freshness():
    entered, failed = [], []
    @asynccontextmanager
    async def audit(db, source):
        entered.append(source)
        try:
            yield object()
        except httpx.HTTPStatusError:
            failed.append(source)
            raise
    error = httpx.HTTPStatusError('upgrade required', request=httpx.Request('GET', 'https://example.test'),
                                 response=httpx.Response(426))
    with patch('src.ingest.underdog.record_run', audit), \
         patch('src.ingest.underdog.get_over_under_lines', AsyncMock(side_effect=error)), \
         patch('src.ingest.underdog.withdraw_absent_props', AsyncMock()) as withdraw, \
         patch('src.ingest.underdog.record_prop_line', AsyncMock()) as record:
        with pytest.raises(httpx.HTTPStatusError):
            await ingest_props(AsyncMock())
    assert entered == failed == ['underdog']
    withdraw.assert_not_called()
    record.assert_not_called()
