"""Next-season keeper opportunity cost in comparable fantasy points.

Scenario arithmetic, not a trained forecast. Inputs must refer to the same
league/scoring/horizon and position-adjusted lineup contribution (not raw
cross-position points or arbitrary trade-market units).
"""
from math import isfinite


def finite_number(value):
    try:
        return type(value) in (int,float) and isfinite(value)
    except OverflowError:
        return False


def value_scenario(league_id, player_id, cost_round, scenario):
    result = {'status': 'withheld', 'actionable': False,
              'model': 'keeper_opportunity_cost_scenario_v1', 'blockers': [],
              'scope': 'Supplied next-season scenario, not independently validated pricing. '
                       'Ranges are sensitivity bounds, not confidence intervals. '
                       'Does not establish eligibility, draft availability or submit a keeper.'}
    if not scenario:
        result['blockers'] = ['next_season_value_evidence_missing']
        return result
    if not isinstance(scenario, dict):
        result['blockers'] = ['invalid_value_evidence']
        return result
    blockers = result['blockers']
    if scenario.get('league_id') != league_id or scenario.get('player_id') != player_id:
        blockers.append('value_identity_mismatch')
    if (type(cost_round) is not int or cost_round < 1
            or type(scenario.get('cost_round')) is not int or scenario.get('cost_round') != cost_round):
        blockers.append('value_cost_round_mismatch')
    season, draft_season = scenario.get('season'), scenario.get('draft_season')
    if (type(season) is not int or type(draft_season) is not int
            or season != draft_season + 1):
        blockers.append('next_season_horizon_required')
    if scenario.get('unit') != 'lineup_points_above_replacement':
        blockers.append('comparable_lineup_value_unit_required')
    for key in ('scoring_basis', 'horizon', 'source'):
        if not isinstance(scenario.get(key), str) or not scenario[key].strip():
            blockers.append(f'{key}_required')
    values = {}
    for side in ('keeper', 'pick'):
        rows = scenario.get(side)
        if not isinstance(rows, dict):
            blockers.append(f'{side}_range_required')
            continue
        numbers = [rows.get(key) for key in ('low', 'base', 'high')]
        if any(not finite_number(v) for v in numbers):
            blockers.append(f'{side}_finite_range_required')
        elif not numbers[0] <= numbers[1] <= numbers[2]:
            blockers.append(f'{side}_ordered_range_required')
        else:
            values[side] = numbers
    if blockers:
        return result
    k, p = values['keeper'], values['pick']
    low, base, high = k[0] - p[2], k[1] - p[1], k[2] - p[0]
    if not all(finite_number(v) for v in (low, base, high)):
        result['blockers'] = ['value_range_overflow']
        return result
    result.update(status='supplied_scenario', season=season, cost_round=cost_round,
                  unit=scenario['unit'], source=scenario['source'],
                  scoring_basis=scenario['scoring_basis'], horizon=scenario['horizon'],
                  surplus={'low': low, 'base': base, 'high': high},
                  break_even_keeper_value=p[1],
                  interpretation='keeper_positive_across_range' if low > 0 else
                  'pick_positive_across_range' if high < 0 else 'sensitive_to_assumptions')
    return result
