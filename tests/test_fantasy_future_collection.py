from unittest.mock import AsyncMock

import httpx
import pytest

from src.ingest import espn_fantasy


@pytest.mark.parametrize('week,expected', [(5, [6, 7]), (17, [18]), (18, [])])
async def test_future_collection_includes_free_agents_and_bounded_weeks(monkeypatch, week, expected):
    from src.services import fantasy_score_history
    snapshots = AsyncMock()
    monkeypatch.setattr(espn_fantasy, '_snapshot', snapshots)
    monkeypatch.setattr(espn_fantasy, '_upsert_league', AsyncMock())
    monkeypatch.setattr(fantasy_score_history, 'collect_espn', AsyncMock())
    monkeypatch.setattr(espn_fantasy, '_parse_matchups', lambda *args: [{'roster_id': 1}])
    requested = []

    async def free_agents(client, league, season, target_week, metadata, projections):
        requested.append(target_week)
        projections['free'] = {'_espn_applied_total': target_week}
        return 1

    monkeypatch.setattr(espn_fantasy, '_fetch_free_agents', free_agents)

    def respond(request):
        target_week = int(request.url.params.get('scoringPeriodId', week))
        return httpx.Response(200, json={'scoringPeriodId': target_week, 'teams': []})

    async with httpx.AsyncClient(base_url='https://example.test', transport=httpx.MockTransport(respond)) as client:
        await espn_fantasy._sync_league(None, client, 2026, 'l', 'espn:l', 'owner')
    assert requested == [week, *expected]
    saved = {call.args[2]: call.args[4] for call in snapshots.call_args_list if call.args[3] == 'projections'}
    assert sorted(saved) == [week, *expected]
    assert all(saved[w]['free']['_espn_applied_total'] == w for w in saved)
