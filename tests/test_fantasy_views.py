from unittest.mock import AsyncMock

import pytest

from src.services import fantasy_views


@pytest.mark.asyncio
async def test_matchup_preserves_missing_slots_and_score_unknowns(monkeypatch):
    data = {
        'week': 4,
        'players': [{'player_id': 'known', 'name': 'Known',
                     'decision_points': 12.5, 'decision_tier': 'estimated_history',
                     'decision_source': 'recent_complete_history_conditional_on_playing'}],
        'rosters': [],
        'matchup_rosters': {
            'mine': {'roster_id': 1, 'starters': ['known', 'unknown']},
            'opponent': {'roster_id': 2, 'starters': ['known'], 'points': 0},
        },
        'matchup': {'status': 'incomplete'}, 'lineup_simulation': {},
    }
    monkeypatch.setattr(fantasy_views, 'data_for', AsyncMock(return_value=data))
    result = await fantasy_views.matchup(None, 'league')
    mine, opponent = result['your_roster'], result['opponent']
    assert len(mine['starters']) == 2
    assert mine['starters'][1]['decision_source'] == 'unresolved_player_identity'
    assert mine['starters'][0]['projection_tier'] == 'estimated_history'
    assert mine['projected_points'] is None
    assert mine['points'] is None
    assert mine['projection_coverage'] == {'available': 1, 'total': 2}
    assert opponent['points'] == 0
    assert opponent['projected_points'] == 12.5
