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
    # No engine research in this checkpoint: the outlook says so instead of showing zeros.
    assert result.outlook.side_a.status == 'insufficient_engine_research' and result.outlook.side_a.lineup_gain is None
    for p in data['players']:
        p['engine'] = {'status': 'research', 'ros_points': 10.0 * (p['player_id'] == 'b') + 4.0,
                       'weeks': [{'week': 6, 'points': 10.0 * (p['player_id'] == 'b') + 4.0, 'environment': 'market_line'}]}
    result = workspace.trade_context(data, request)
    assert (result.outlook.side_a.lineup_gain, result.outlook.side_b.lineup_gain) == (10.0, -10.0)
    assert result.outlook.side_a.by_position['QB'] == 10.0 and result.outlook.player_ros_points == {'a': 4.0, 'b': 14.0}
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


def engine_data():
    def p(pid, pos, ros, roster_ids, weekly=None, weeks=None):
        return dict(player_id=pid, name=pid, position=pos, roster_ids=roster_ids, locked=False, weekly_points=weekly,
                    engine={'status': 'research', 'ros_points': ros, 'week_points': 5.0, 'ros_games': 10,
                            'ros_lined_games': 1, 'weeks': weeks or [{'week': 6, 'points': 5.0, 'environment': 'market_line'}],
                            'generated_at': '2026-10-12T00:00:00Z'} if ros is not None else {'status': 'position_not_modeled'})
    return {'players': [p('mine_qb', 'QB', 10, [1]), p('mine_wr', 'WR', 60, [1]), p('mine_wr2', 'WR', 90, [1]),
                        p('fa_wr', 'WR', 75, [], weeks=[{'week': 6, 'points': 9.0, 'environment': 'market_line'}]),
                        p('theirs', 'WR', 200, [2]), p('fa_qb', 'QB', 100, []), p('fa_te', 'TE', 66, []),
                        p('mine_k', 'K', None, [1], weekly=6.0), p('fa_k', 'K', None, [], weekly=9.5)],
            'roster_positions': ['QB', 'WR', 'K', 'BN'],
            'waiver_settings': {'platform': 'sleeper', 'waiver_type': 0, 'waiver_clear_days': 2},
            'rosters': [{'roster_id': 1, 'is_mine': True, 'waiver_position': 3,
                         'player_ids': ['mine_qb', 'mine_wr', 'mine_wr2', 'mine_k']},
                        {'roster_id': 2, 'player_ids': ['theirs']}],
            'read_model': {'generated_at': '2026-10-12T00:00:00Z', 'expires_at': '2026-10-12T00:02:00Z'}}


def test_waiver_guidance_presents_stored_rows_revalidated_against_ownership():
    data = engine_data()
    data['waiver_guidance'] = {'status': 'research', 'rows': [
        {'add_id': 'fa_wr', 'drop_id': 'mine_wr', 'lineup_gain': 16.0, 'week': 6, 'week_gain': 4.0, 'weeks': 12, 'weeks_improved': 9},
        {'add_id': 'fa_te', 'drop_id': 'mine_wr', 'lineup_gain': 6.0, 'week': 6, 'week_gain': 1.0, 'weeks': 12, 'weeks_improved': 3},
        {'add_id': 'theirs', 'drop_id': 'mine_wr', 'lineup_gain': 50.0, 'week': 6, 'week_gain': 5.0, 'weeks': 12, 'weeks_improved': 9},
        {'add_id': 'fa_qb', 'drop_id': 'not_mine', 'lineup_gain': 50.0, 'week': 6, 'week_gain': 5.0, 'weeks': 12, 'weeks_improved': 9},
        {'add_id': 'fa_k', 'drop_id': 'mine_k', 'lineup_gain': None, 'week': None, 'week_gain': 3.5, 'stream': True}]}
    view = workspace.overview('league', data).engine_waivers
    assert (view.status, view.waiver_type, view.waiver_position, view.teams) == ('research', 'rolling', 3, 2)
    assert [(r.add.player_id, r.tier) for r in view.rows] == [('fa_wr', 'priority'), ('fa_te', 'consider'), ('fa_k', 'stream')]
    assert 'best starting lineup across the next 12 weeks' in view.rows[0].reasons[0]
    assert 'Cross-position' in view.rows[1].reasons[1]


def test_waiver_guidance_fails_closed():
    data = engine_data()
    assert workspace.overview('league', data).engine_waivers.status == 'unavailable'
    data['waiver_guidance'] = {'status': 'research', 'rows': []}
    assert workspace.overview('league', data).engine_waivers.status == 'no_positive_research_moves'
    data['rosters'][0]['is_mine'] = False
    assert workspace.overview('league', data).engine_waivers.status == 'owner_roster_unresolved'


def test_outcome_view_exposes_research_and_names_changes_without_validation_claims():
    data = engine_data()
    data['outcome_simulation'] = {'status': 'estimated_research', 'reason': 'r', 'known_final_starters': 2,
        'model': {'blend_status': 'provider_only', 'validation': {'matchups': {'n': 24, 'correlated': {'brier': 0.22}, 'coin': {'brier': 0.25}}}},
        'current': {'win_probability': 0.41, 'mean': 101.0, 'p10': 80.0, 'p90': float('nan')},
        'max_win_probability_lineup': {'win_probability': 0.47, 'expected_points': 99.0,
                                       'changes': [{'slot': 'WR', 'start': 'fa_wr', 'replaces': 'mine_wr'}]},
        'player_ranges': {'mine_wr': {'mean': 9.0, 'p10': 2.0, 'p50': 8.0, 'p90': 17.0, 'boom_probability': .1,
                                      'bust_probability': .3, 'basis': 'provider'}}}
    view = workspace.overview('league', data).outcomes
    assert view.win_probability == 0.41 and view.p90 is None and view.validated is False
    assert view.best_changes[0].start_name == 'fa_wr' and view.validation_matchups == 24
    data['outcome_simulation'] = {'status': 'withheld', 'reason': 'starter_blockers',
                                  'blockers': [{'name': 'X', 'reason': 'game_in_progress'}]}
    view = workspace.overview('league', data).outcomes
    assert view.win_probability is None and view.blockers == ['X: game in progress']


def test_positional_strength_ranks_best_starters_and_skips_incomplete_rosters():
    data = engine_data()
    data['roster_positions'] = ['QB', 'WR', 'BN']
    data['rosters'].append({'roster_id': 3, 'player_ids': ['fa_qb']})  # no WR with research: unranked
    data['players'].append(dict(player_id='theirs_qb', name='q', position='QB', roster_ids=[2],
                                engine={'status': 'research', 'ros_points': 50}))
    data['rosters'][1]['player_ids'].append('theirs_qb')
    view = workspace.overview('league', data).strength
    by = {p.position: p for p in view.positions}
    assert by['WR'].value == 90 and by['WR'].rank == 2 and by['WR'].teams == 2
    assert by['QB'].rank == 3 and by['QB'].league_best == 100
    assert view.overall_rank == 2 and view.teams == 2


def test_game_log_comes_from_league_scored_history_only():
    detail = workspace.player_detail({'player_id': 'x', 'distribution_evidence': {'evidence': [
        {'week': 3, 'points': 12.5}, {'week': 4, 'points': float('nan')}]}})
    assert [(w.week, w.points) for w in detail.game_log] == [(3, 12.5)]


def test_engine_qualification_reads_latest_reports_and_never_promotes(tmp_path):
    import json
    assert [(t.status, t.required_weeks) for t in workspace.qualification_tracks(tmp_path)] == [('no_report_yet', 6), ('no_report_yet', 5)]
    promo = {'eligible_for_owner_review': False, 'blockers': ['needs_6_graded_weeks_has_2'],
             'pool': {'n': 40, 'weeks': [6, 7], 'engine_mae': 5.1, 'sleeper_mae': 5.3, 'paired_difference': -0.2, 'ci': [-0.5, 0.1]}}
    for sub in ('reports', 'depth/reports'):
        (tmp_path / sub).mkdir(parents=True)
        (tmp_path / sub / '20261001T000000.json').write_text(json.dumps({'status': 'old'}))
        (tmp_path / sub / '20261012T000000.json').write_text(json.dumps({
            'status': 'prospective_research', 'generated_at': '2026-10-12T00:00:00+00:00', 'version': 'v', 'engine_forecasts': 9,
            'statuses': {'graded': 40}, 'promotion': promo, 'candidate_blend': {'promotion': {'blockers': ['needs_6_graded_weeks_has_0']}}}))
    tracks = workspace.qualification_tracks(tmp_path)
    assert [t.name for t in tracks] == ['Projection engine v1', 'Projection engine v1 · Sleeper blend', 'Engine + depth chart/status']
    assert (tracks[0].graded_weeks, tracks[0].required_weeks, tracks[0].pool.ci, tracks[0].serving_promoted) == (2, 6, [-0.5, 0.1], False)
    assert tracks[1].graded_weeks == 0 and tracks[1].blockers == ['needs_6_graded_weeks_has_0']
    (tmp_path / 'depth/reports/20261013T000000.json').write_text('{not json')
    assert workspace.qualification_tracks(tmp_path)[-1].status == 'report_unreadable'


def test_win_probability_check_reads_the_latest_report(tmp_path):
    import json
    assert workspace.win_probability_check(tmp_path).status == 'no_report_yet'
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'reports' / '20261020T000000.json').write_text(json.dumps({
        'status': 'prospective_research', 'captured_matchups': 4, 'statuses': {'graded': 2, 'awaiting_final_week': 2},
        'summary': {'n': 2, 'brier': 0.21, 'log_loss': 0.6}}))
    check = workspace.win_probability_check(tmp_path)
    assert (check.graded, check.brier, check.coin_flip_brier, check.captured_matchups) == (2, 0.21, 0.25, 4)


def test_waiver_rows_note_sleeper_trending_and_list_unrostered_risers():
    data = engine_data()
    data['waiver_guidance'] = {'status': 'research', 'rows': [
        {'add_id': 'fa_wr', 'drop_id': 'mine_wr', 'lineup_gain': 16.0, 'week': 6, 'week_gain': 4.0, 'weeks': 12, 'weeks_improved': 9}]}
    data['_trending'] = {'fa_wr': 5400, 'fa_te': 900, 'theirs': 12000, 'mine_k': 50}
    view = workspace.overview('league', data).engine_waivers
    assert view.rows[0].trending_adds == 5400 and 'Trending on Sleeper: 5,400 adds' in view.rows[0].reasons[-1]
    assert [(t.player.player_id, t.adds) for t in view.trending] == [('fa_wr', 5400), ('fa_te', 900)]  # rostered excluded
