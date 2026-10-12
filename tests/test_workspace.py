"""Offline tests: v2 must never fall back to an expensive model build."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException, Response
from src.api.routers import workspace


def test_missing_checkpoint_is_not_an_empty_success():
    result = workspace.overview('league', None)
    assert result.status == 'updating'
    assert result.actionable is False
    assert result.generated_at is None


def test_compact_view_preserves_zero_unknown_lock_and_evidence():
    data = {'players': [dict(player_id='a', name='A', decision_points=0,
                            decision_tier='estimated_history', locked=True)],
            'lineup_decision': {'status': 'candidate', 'lineup': [
                dict(slot='QB', player_id='a'), dict(slot='RB', player_id='missing'),
                dict(slot='WR', player_id=None)]},
            'read_model': {'generated_at': '2026-10-03T00:00:00+00:00',
                           'expires_at': '2026-10-03T00:02:00+00:00'},
            'recipe_version': 'retained', 'scoring_contract_hash': 'rules'}
    result = workspace.overview('league', data)
    assert result.starters[0].points == 0
    assert result.starters[0].locked is True
    assert result.starters[1].points is None
    assert result.starters[2].name == 'Unfilled slot'
    assert result.recipe_version == 'retained'
    assert result.scoring_contract_hash == 'rules'
    assert 'players' not in result.model_dump()


@pytest.mark.asyncio
async def test_route_reads_checkpoint_only(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(sport='nfl')))
    read = AsyncMock(return_value=None)
    monkeypatch.setattr(workspace, 'read', read)
    response = Response()
    result = await workspace.league_overview('league', response, db)
    read.assert_awaited_once_with(db, 'league')
    assert result.status == 'updating'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Retry-After'] == '30'


@pytest.mark.asyncio
async def test_unknown_league_does_not_read_checkpoint(monkeypatch):
    read = AsyncMock()
    monkeypatch.setattr(workspace, 'read', read)
    with pytest.raises(HTTPException) as exc:
        await workspace.league_overview('missing', Response(), SimpleNamespace(get=AsyncMock(return_value=None)))
    assert exc.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_is_authenticated_and_has_no_mutation_routes():
    from src.api.workspace_app import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/v2/fantasy/leagues')).status_code == 401
        assert (await client.post('/api/v1/fantasy/sync/espn')).status_code == 404
        assert (await client.post('/api/v2/fantasy/leagues')).status_code == 405


def test_generated_contract_is_current():
    from scripts.generate_workspace_types import TARGET, render
    assert TARGET.read_text() == render()


def matchup_data():
    return {'players': [dict(player_id=pid, name=pid.upper(), decision_points=value,
                            decision_tier='estimated', locked=False)
                        for pid, value in [('a', 0), ('b', 12), ('c', 15)]],
            'roster_positions': ['WR', 'FLEX', 'BN'],
            'matchup_rosters': {'mine': {'roster_id': 1, 'starters': ['a', 'b'], 'points': 0},
                               'opponent': None},
            'rosters': [{'roster_id': 1, 'name': 'My team'}],
            'matchup': {'status': 'withheld', 'your_pregame_projection': 12},
            'lineup_decision': {'status': 'lock_preserving_candidate', 'lineup': [
                {'slot': 'WR', 'player_id': 'c'}, {'slot': 'FLEX', 'player_id': 'b'}]},
            'read_model': {'generated_at': '2026-10-04T00:00:00Z',
                           'expires_at': '2026-10-04T00:02:00Z'}}


def test_matchup_scores_and_projections_are_separate_and_missing_opponent_unknown():
    result = workspace.overview('league', matchup_data())
    assert result.matchup.mine.recorded_points == 0
    assert result.matchup.mine.pregame_points is None
    assert result.matchup.mine.starters[0].points == 0
    assert result.matchup.opponent is None
    assert result.matchup.mine.name == 'My team'
    assert [p.player_id for p in result.lineup_changes.start] == ['c']
    assert [p.player_id for p in result.lineup_changes.bench] == ['a']
    assert result.actionable is False


def test_flex_rearrangement_is_not_a_player_change():
    data = matchup_data()
    data['lineup_decision']['lineup'][0]['player_id'] = 'b'
    data['lineup_decision']['lineup'][1]['player_id'] = 'a'
    changes = workspace.overview('league', data).lineup_changes
    assert changes.status == 'available'
    assert changes.start == changes.bench == []


@pytest.mark.parametrize('case', ['locked_drop', 'locked_add', 'unknown_lock', 'missing_player',
                                  'duplicate', 'missing_slot', 'stale', 'locked_rearranged'])
def test_changes_fail_closed(case):
    data = matchup_data()
    if case == 'locked_drop':
        data['players'][0]['locked'] = True
    elif case == 'locked_add':
        data['players'][2]['locked'] = True
    elif case == 'unknown_lock':
        del data['players'][2]['locked']
    elif case == 'missing_player':
        data['players'].pop()
    elif case == 'duplicate':
        data['lineup_decision']['lineup'][0]['player_id'] = 'b'
    elif case == 'missing_slot':
        data['matchup_rosters']['mine']['starters'].pop()
    elif case == 'stale':
        data['lineup_decision']['status'] = 'stale_inputs'
    else:
        data['players'][1]['locked'] = True
        data['lineup_decision']['lineup'][0]['player_id'] = 'b'
        data['lineup_decision']['lineup'][1]['player_id'] = 'c'
    assert workspace.overview('league', data).lineup_changes.status == 'withheld'


def test_nonfinite_scores_do_not_leak_into_json():
    data = matchup_data()
    data['matchup_rosters']['mine']['points'] = float('nan')
    data['players'][0]['decision_points'] = float('inf')
    result = workspace.overview('league', data)
    assert result.matchup.mine.recorded_points is None
    assert result.matchup.mine.starters[0].points is None
    result.model_dump_json()


def waiver_data():
    data = matchup_data()
    data['rosters'][0].update(is_mine=True, player_ids=['a', 'b', 'd'])
    data['players'].append(dict(player_id='d', name='D', locked=False))
    data['players'][2].update(replacement_pool_member=True, roster_ids=[])
    data['waivers'] = {'status': 'lock_preserving_candidate', 'moves': [
        dict(add_id='c', drop_id='d', lineup_gain=2.5, scope='unstarted_slots_only')]}
    return data


def test_waiver_scope_and_unpriced_roster_details():
    result = workspace.overview('league', waiver_data())
    assert len(result.waivers.moves) == 1
    assert result.waivers.moves[0].unstarted_slot_gain == 2.5
    assert result.waivers.moves[0].drop.points is None
    assert result.waivers.moves[0].recommendation_status == 'research_only'
    assert any('cost of releasing' in warning for warning in result.waivers.moves[0].retention_warnings)
    assert {p.player_id for p in result.roster_players} == {'a', 'b', 'd'}
    assert result.roster_players[0].points == 0
    assert result.roster_players[0].complete_scored_games is None


def test_waiver_retention_risk_exposes_cross_position_and_injury_cost():
    data = waiver_data()
    data['players'][2]['position'] = 'DEF'
    data['players'][-1].update(position='QB', injury_status='IR')
    move = workspace.overview('league', data).waivers.moves[0]
    assert any('different positions' in warning for warning in move.retention_warnings)
    assert any('temporary absence' in warning for warning in move.retention_warnings)
    assert move.unstarted_slot_gain == 2.5


def test_equivalent_drops_are_revalidated_against_current_roster_and_locks():
    data = waiver_data()
    data['rosters'][0]['player_ids'].extend(['e','locked'])
    data['players'].extend([dict(player_id='e',name='E',locked=False),
                            dict(player_id='locked',name='Locked',locked=True)])
    data['waivers']['moves'][0]['equivalent_drop_ids']=['d','e','e','a','locked','absent','c']
    move=workspace.overview('league',data).waivers.moves[0]
    assert [p.player_id for p in move.equivalent_drops]==['e']
    assert any('Multiple drops' in warning for warning in move.retention_warnings)


@pytest.mark.parametrize('drop_ros', [50, 150])
def test_ros_research_never_qualifies_a_waiver_recommendation(drop_ros):
    data = waiver_data()
    for player, points in [(data['players'][2], 100), (data['players'][-1], drop_ros)]:
        player.update(position='RB', identity_status='exact', ros={
            'status': 'complete_schedule_candidate', 'full_ros_value': points,
            'per_game': {'status': 'candidate', 'missing_scoring_keys': []}})
    move = workspace.overview('league', data).waivers.moves[0]
    assert move.recommendation_status == 'research_only'
    assert any('higher conditional ROS' in warning for warning in move.retention_warnings) == (drop_ros > 100)
    assert not any('cost of releasing' in warning for warning in move.retention_warnings)


@pytest.mark.parametrize('case', ['locked', 'owned_add', 'starter_drop', 'missing_add',
                                  'wrong_scope', 'nan_gain', 'stale', 'ambiguous_roster'])
def test_waiver_comparisons_fail_closed(case):
    data = waiver_data()
    move = data['waivers']['moves'][0]
    if case == 'locked':
        data['players'][2]['locked'] = True
    elif case == 'owned_add':
        data['players'][2]['roster_ids'] = [2]
    elif case == 'starter_drop':
        move['drop_id'] = 'a'
    elif case == 'missing_add':
        move['add_id'] = 'missing'
    elif case == 'wrong_scope':
        move['scope'] = 'ros'
    elif case == 'nan_gain':
        move['lineup_gain'] = float('nan')
    elif case == 'stale':
        data['waivers']['status'] = 'withheld_stale_inputs'
    else:
        data['rosters'].append(dict(is_mine=True, player_ids=['c']))
    result = workspace.overview('league', data)
    assert result.waivers.moves == []
    assert result.waivers.excluded_moves == 1


def test_missing_roster_player_stays_visible_as_unresolved():
    data = waiver_data()
    data['rosters'][0]['player_ids'].append('missing')
    player = next(p for p in workspace.overview('league', data).roster_players if p.player_id == 'missing')
    assert player.name == 'Unresolved player'
    assert player.locked and player.points is None


@pytest.mark.parametrize('gap', [None, 'identity', 'schedule', 'history', 'scoring'])
def test_ros_presentation_never_upgrades_partial_evidence(gap):
    player = {'player_id': 'a', 'identity_status': 'exact', 'ros': {
        'status': 'complete_schedule_candidate', 'full_ros_value': 0,
        'known_schedule_subtotal': 25, 'known_remaining_games': 10,
        'unknown_kickoffs': 2, 'through_week': 18,
        'per_game': {'status': 'candidate', 'missing_scoring_keys': []}}}
    if gap == 'identity':
        player['identity_status'] = 'unresolved'
    elif gap == 'schedule':
        player['ros']['status'] = 'known_schedule_only'
    elif gap == 'history':
        player['ros']['per_game']['status'] = 'insufficient_history'
    elif gap == 'scoring':
        player['ros']['per_game']['missing_scoring_keys'] = ['bonus']
    result = workspace.player_detail(player)
    assert result.ros_points == (0 if gap is None else None)
    assert result.known_schedule_subtotal == 25
    assert result.unknown_kickoffs == 2


def test_missing_ros_is_unknown_not_zero():
    result = workspace.player_detail({'player_id': 'a'})
    assert result.ros_points is None and result.known_remaining_games is None


def test_catalog_corroborates_ownership_and_preserves_missing_players():
    data = {'rosters': [dict(roster_id=1, is_mine=True, name='Mine', player_ids=['a', 'missing']),
                        dict(roster_id=2, name='Other', player_ids=['b'])]}
    by_id = {pid: dict(player_id=pid, name=pid, roster_ids=owners)
             for pid, owners in [('a', [1]), ('b', [2]), ('c', []), ('conflict', [1])]}
    result = {p.player_id: p for p in workspace.comparison_context(data, by_id)}
    assert result['a'].ownership == 'your_roster'
    assert result['b'].ownership == 'other_roster'
    assert result['b'].roster_names == ['Other']
    assert result['c'].ownership == 'unrostered_snapshot'
    assert result['conflict'].ownership == result['missing'].ownership == 'unknown'
    assert result['missing'].points is None
    data['rosters'][1]['player_ids'].append('a')
    assert next(p for p in workspace.comparison_context(data, by_id) if p.player_id == 'a').ownership == 'unknown'


def test_absent_rosters_do_not_establish_free_agency():
    assert workspace.comparison_context({}, {'a': {'player_id': 'a', 'roster_ids': []}})[0].ownership == 'unknown'


def trade_data():
    data = matchup_data()
    data['roster_positions'] = ['QB']
    data['coverage'] = {'stale_inputs': False}
    data['rosters'] = [dict(roster_id=i, name=str(i), player_ids=[pid], is_mine=i == 1)
                       for i, pid in enumerate(['a', 'b', 'c'], 1)]
    for i, p in enumerate(data['players'], 1):
        p.update(position='QB', roster_ids=[i], identity_status='exact', ros={
            'status':'complete_schedule_candidate', 'full_ros_value': i * 100,
            'per_game': {'status':'candidate', 'per_game':i * 10, 'missing_scoring_keys':[]}})
    return data


def test_checkpoint_trade_reuses_evaluator_without_promoting():
    data = trade_data()
    request = workspace.TradeRequest(generated_at=data['read_model']['generated_at'], side_a=['a'], side_b=['b'])
    result = workspace.trade_context(data, request)
    assert result.status == 'research_candidate' and result.actionable is False
    assert result.side_a.conditional_lineup_gain == 10
    assert result.side_b.conditional_lineup_gain == -10
    data['players'][0]['identity_status'] = 'unresolved'
    result = workspace.trade_context(data, request)
    assert result.status == 'withheld'
    assert result.side_a.conditional_lineup_gain is None


@pytest.mark.parametrize('case', ['changed', 'duplicate', 'unknown', 'ownership', 'uneven', 'same_roster'])
def test_trade_package_guards(case):
    data = trade_data()
    a, b = ['a'], ['b']
    when = data['read_model']['generated_at']
    if case == 'changed': when = '2026-10-03T00:00:00Z'
    elif case == 'duplicate': b = ['a']
    elif case == 'unknown': b = ['missing']
    elif case == 'ownership': data['players'][1]['roster_ids'] = []
    elif case == 'uneven': b = ['b', 'c']
    else:
        data['rosters'][0]['player_ids'].append('b')
        data['rosters'][1]['player_ids'] = []
        data['players'][1]['roster_ids'] = [1]
    result = workspace.trade_context(data, workspace.TradeRequest(generated_at=when, side_a=a, side_b=b))
    assert result.status == 'withheld' and result.blockers


@pytest.mark.asyncio
async def test_trade_endpoint_never_rebuilds_missing_checkpoint(monkeypatch):
    monkeypatch.setattr(workspace, 'read', AsyncMock(return_value=None))
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(sport='nfl')))
    with pytest.raises(HTTPException) as exc:
        await workspace.trade_preview('league', workspace.TradeRequest(
            generated_at='2026-10-04T00:00:00Z', side_a=['a'], side_b=['b']), Response(), db)
    assert exc.value.status_code == 409


def uneven_data():
    from copy import deepcopy
    data = trade_data()
    data['rosters'] = [dict(roster_id=1,name='A',is_mine=True,player_ids=['a','d']),
                       dict(roster_id=2,name='B',player_ids=['b','c'])]
    data['players'][2]['roster_ids'] = [2]
    for pid, owners in [('d',[1]), ('e',[])]:
        player = deepcopy(data['players'][0])
        player.update(player_id=pid,name=pid,roster_ids=owners,locked=False)
        data['players'].append(player)
    return data


def test_explicit_uneven_trade_balances_both_rosters():
    data = uneven_data()
    request = workspace.TradeRequest(generated_at=data['read_model']['generated_at'],
        side_a=['a'],side_b=['b','c'],a={'drop':['d']},b={'add':['e']})
    result = workspace.trade_context(data, request)
    assert result.status == 'research_candidate'
    assert result.side_a.roster_size_before == result.side_a.roster_size_after == 2
    assert result.side_b.roster_size_before == result.side_b.roster_size_after == 2


@pytest.mark.parametrize('case',['duplicate','owned_add','locked','unknown','wrong_drop','unbalanced','injured'])
def test_uneven_adjustments_remain_gated(case):
    data = uneven_data()
    a,b = {'drop':['d']},{'add':['e']}
    if case == 'duplicate': a['add'] = ['e']
    elif case == 'owned_add': b['add'] = ['d']; a = {}
    elif case == 'locked': data['players'][-1]['locked'] = True
    elif case == 'unknown': b['add'] = ['unknown']
    elif case == 'wrong_drop': a,b = {},{'drop':['d'],'add':['e']}
    elif case == 'unbalanced': b = {}
    else: data['players'][-1]['injury_status'] = 'OUT'
    result = workspace.trade_context(data, workspace.TradeRequest(
        generated_at=data['read_model']['generated_at'],side_a=['a'],side_b=['b','c'],a=a,b=b))
    assert result.status == 'withheld' and result.blockers
    assert result.side_a is None or result.side_a.conditional_lineup_gain is None


def test_trade_reports_supporting_player_evidence_without_numeric_gain():
    data = uneven_data()
    data['players'][-2]['identity_status'] = 'unresolved'
    data['players'][1]['injury_status'] = 'OUT'
    result = workspace.trade_context(data, workspace.TradeRequest(
        generated_at=data['read_model']['generated_at'],side_a=['a'],side_b=['b']))
    assert result.status == 'withheld'
    assert 'd' in result.side_a.missing_players
    assert 'B' in result.side_b.availability_review_players
    assert result.side_a.conditional_lineup_gain is None
    assert result.side_b.conditional_lineup_gain is None
