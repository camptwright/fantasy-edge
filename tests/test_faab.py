from src.services.faab import bids, budgets, history_share

ROSTERS = [{'roster_id': 1, 'settings': {'waiver_budget_used': 20}},
           {'roster_id': 2, 'settings': {'waiver_budget_used': 90}},
           {'roster_id': 3, 'settings': {'waiver_budget_used': 60}}]
ROWS = [{'add_id': 'a', 'drop_id': 'x', 'lineup_gain': 20.0, 'weeks': 4},
        {'add_id': 'b', 'drop_id': 'x', 'lineup_gain': 5.0, 'weeks': 4},
        {'add_id': 'k', 'drop_id': 'y', 'lineup_gain': None, 'stream': True}]


def test_only_bidding_leagues_get_budgets():
    assert budgets({'waiver_type': 0, 'waiver_budget': 100}, ROSTERS) is None
    money = budgets({'waiver_type': 2, 'waiver_budget': 100}, ROSTERS)
    assert money['remaining'] == {1: 80, 2: 10, 3: 40}
    assert bids(ROWS, None, 1, 6)['status'] == 'not_a_faab_league'


def test_bids_pace_the_budget_and_never_exceed_the_richest_rival_plus_one():
    money = budgets({'waiver_type': 2, 'waiver_budget': 100}, ROSTERS)
    plan = bids(ROWS, money, 1, 7, playoff_start=15)
    assert plan['weeks_left'] == 8 and plan['remaining_budget'] == 80
    best, small = plan['rows']
    # best add: 4-week horizon over 8 weeks left -> half the remaining budget, capped at 41
    assert best['share_of_remaining'] == 0.5 and best['bid_high'] == 41 and best['bid_low'] == 20
    assert small['bid_low'] < best['bid_low']
    assert all(r['add_id'] != 'k' for r in plan['rows'])


def test_history_reports_median_winning_share():
    tx = [{'type': 'waiver', 'status': 'complete', 'settings': {'waiver_bid': 10}},
          {'type': 'waiver', 'status': 'complete', 'settings': {'waiver_bid': 30}},
          {'type': 'waiver', 'status': 'failed', 'settings': {'waiver_bid': 99}},
          {'type': 'free_agent', 'status': 'complete', 'settings': None}]
    assert history_share(tx, 100) == {'claims': 2, 'median_share': 0.2}
