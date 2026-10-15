from types import SimpleNamespace

from src.services.draft_picks import inventory, ownership, price, tiers
from src.services.dynasty_trade_planning import plan


def roster(rid, wins, losses, fpts=100):
    return SimpleNamespace(roster_id=rid, settings={'wins': wins, 'losses': losses, 'fpts': fpts})


MARKET = {'captured_at': '2026-10-14T00:00:00+00:00', 'rows': [
    {'position': 'PICK', 'sleeper_id': 'FP_2027_early_0', 'value': 5000},
    {'position': 'PICK', 'sleeper_id': 'FP_2027_late_0', 'value': 2500},
    {'position': 'PICK', 'sleeper_id': 'FP_2027_1', 'value': 3000},
    {'position': 'PICK', 'sleeper_id': 'FP_2028_1', 'value': 2200},
    {'position': 'WR', 'sleeper_id': '123', 'value': 9000}]}


def test_traded_pick_moves_to_current_owner_and_past_drafts_are_ignored():
    traded = [{'season': '2027', 'round': 1, 'roster_id': 1, 'owner_id': 2},
              {'season': '2026', 'round': 1, 'roster_id': 2, 'owner_id': 1}]
    picks = {p['id']: p for p in ownership(2026, 2, [1, 2], traded)}
    assert len(picks) == 3 * 2 * 2
    assert picks['2027-1-1']['owner_roster_id'] == 2
    assert picks['2027-1-2']['owner_roster_id'] == 2
    assert not any(p['season'] == 2026 for p in picks.values())


def test_tiers_need_enough_games_and_put_worst_record_early():
    assert tiers([roster(1, 1, 1), roster(2, 2, 0), roster(3, 0, 2)]) == {}
    t = tiers([roster(1, 4, 1), roster(2, 1, 4), roster(3, 2, 3, 900), roster(4, 2, 3, 500), roster(5, 3, 2), roster(6, 5, 0)])
    assert t[2] == 'early' and t[4] == 'early' and t[6] == 'late'


def test_next_draft_uses_tier_later_drafts_use_round_average():
    values = {r['sleeper_id']: r['value'] for r in MARKET['rows']}
    assert price({'season': 2027, 'round': 1, 'original_roster_id': 2}, values, 2027, {2: 'early'})['value'] == 5000
    assert price({'season': 2027, 'round': 1, 'original_roster_id': 2}, values, 2027, {})['basis'] == 'generic_round'
    assert price({'season': 2028, 'round': 1, 'original_roster_id': 2}, values, 2027, {2: 'early'})['value'] == 2200
    assert price({'season': 2029, 'round': 3, 'original_roster_id': 2}, values, 2027, {})['value'] is None


def test_inventory_requires_synced_ownership():
    league = SimpleNamespace(settings={'draft_rounds': 1}, season='2026')
    assert inventory(league, [roster(1, 4, 1)], None, MARKET)['status'] == 'ownership_not_synced'
    result = inventory(league, [roster(1, 4, 1), roster(2, 1, 4)], [], MARKET)
    assert result['status'] == 'observed' and len(result['picks']) == 6


def trade_data():
    return {'players': [{'player_id': 'x'}, {'player_id': 'y'}],
            'rosters': [{'roster_id': 1, 'player_ids': ['x']}, {'roster_id': 2, 'player_ids': ['y']}]}


def test_plan_prices_verified_picks_and_rejects_picks_the_side_does_not_own():
    inv = {'picks': [{'id': '2027-1-2', 'season': 2027, 'round': 1, 'original_roster_id': 2, 'owner_roster_id': 2,
                      'value': 5000, 'market_id': 'FP_2027_early_0', 'basis': 'early_round_estimated_from_current_standings'}]}
    market = {'status': 'observed', 'players': [{'player_id': 'x', 'value': 6000, 'identity_status': 'exact'},
                                                 {'player_id': 'y', 'value': 1000, 'identity_status': 'exact'}]}
    ok = plan(trade_data(), ['x'], ['y'], picks=[{'side': 'b', 'pick_id': '2027-1-2'}], market=market, inventory=inv)
    assert ok['status'] == 'scenario' and ok['pick_ownership_verified'] is True
    assert ok['packages']['b']['scenario_package_index'] == 6000
    assert ok['packages']['b']['picks'][0]['valuation_type'] == 'fantasycalc_observed'
    assert ok['side_a_market_index_change'] == 0
    wrong = plan(trade_data(), ['x'], ['y'], picks=[{'side': 'a', 'pick_id': '2027-1-2'}], market=market, inventory=inv)
    assert wrong['status'] == 'pick_not_owned_by_giving_side'
    assert plan(trade_data(), ['x'], ['y'], picks=[{'side': 'a', 'pick_id': 'nope'}], market=market, inventory=inv)['status'] == 'unknown_pick'


def test_typed_picks_stay_unverified_scenarios():
    market = {'status': 'observed', 'players': []}
    result = plan(trade_data(), ['x'], ['y'], picks=[{'side': 'a', 'season': 2027, 'round': 2, 'value': 900, 'source': 'mine'}], market=market)
    assert result['pick_ownership_verified'] is False
    assert result['packages']['a']['picks'][0]['valuation_type'] == 'user_supplied_market_index_scenario'
