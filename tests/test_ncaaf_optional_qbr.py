"""ESPN passing rows may omit trailing QBR, never arbitrary columns."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.ingest.ncaaf_player_stats import _ingest_category


@pytest.mark.parametrize('suffix,values,expected', [
    (['adjQBR'], ['11/21', '140', '6.7', '0', '0'], 5),
    (['adjQBR'], ['11/21', '140', '6.7', '0', '0', '45.2'], 5),
    ([], ['11/21', '140', '6.7', '0', '0'], 5),
    (['adjQBR'], ['11/21', '140', '6.7', '0'], 0),
    (['unknown'], ['11/21', '140', '6.7', '0', '0'], 0),
    ([], ['11/21', '140', '6.7', '0'], 0),
])
async def test_optional_qbr(monkeypatch, suffix, values, expected):
    import uuid
    player = SimpleNamespace(id=uuid.uuid4())
    resolve = AsyncMock(return_value=player)
    monkeypatch.setattr('src.ingest.ncaaf_player_stats.resolve_player', resolve)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
    category = {'name': 'passing', 'keys': ['completions/passingAttempts',
        'passingYards', 'yardsPerPassAttempt', 'passingTouchdowns', 'interceptions']+suffix,
        'athletes': [{'athlete': {'id': '123', 'displayName': 'Test Player'}, 'stats': values}]}
    assert await _ingest_category(db, uuid.uuid4(), category) == expected
    if expected:
        inserted = {call.args[0].compile().params['stat_type']:
                    call.args[0].compile().params['value'] for call in db.execute.call_args_list}
        assert inserted == {'passing_completions': 11., 'passing_attempts': 21.,
                            'passing_yards': 140., 'passing_touchdowns': 0.,
                            'passing_interceptions': 0.}
    else:
        resolve.assert_not_called()
