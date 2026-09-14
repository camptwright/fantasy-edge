"""Fixed research recipes. No serving imports, tuning, or automatic promotion."""
import math
import statistics

OPPORTUNITY = {'hits': 'plate_appearances', 'home_runs': 'plate_appearances',
    'rbis': 'plate_appearances', 'runs': 'plate_appearances', 'total_bases': 'plate_appearances',
    'strikeouts': 'pitching_outs', 'receptions': 'targets', 'receiving_yards': 'targets',
    'rushing_yards': 'rushing_attempts', 'passing_yards': 'passing_attempts'}


def normal(mean, sigma, line):
    return .5*math.erfc((line-mean)/(sigma*math.sqrt(2)))


def candidates(history, stat, season, as_of, line):
    """History entries: time, game_id, season, game_type, values (explicit only).

    Season prior contributes eight pseudo-games; workload blend has 50% weight
    and a one-sigma cap. Those constants are frozen before inspecting scores.
    Pitcher role means last observed starter/reliever status, NOT future status.
    """
    rows = sorted((r for r in history if r['time'] < as_of and r['season'] <= season and
                   r['game_type'] != 'PRE' and stat in r['values'] and
                   math.isfinite(r['values'][stat])), key=lambda r: (r['time'], r['game_id']))
    if len(rows) < 8 or not math.isfinite(line):
        return {}, 'insufficient_history'
    values = [r['values'][stat] for r in rows]
    mean, sigma = statistics.fmean(values), statistics.pstdev(values)
    if sigma <= 0:
        return {}, 'zero_variance'
    result = {'repaired_history_control_v1': normal(mean, sigma, line)}
    prior = [r['values'][stat] for r in rows if r['season'] == season-1]
    current = [r['values'][stat] for r in rows if r['season'] == season]
    if len(prior) >= 8 and current:
        seasonal = (8*statistics.fmean(prior)+sum(current))/(8+len(current))
        result['season_shrinkage_normal_v1'] = normal(seasonal, sigma, line)
    usage = OPPORTUNITY.get(stat)
    role_rows = rows
    if stat == 'strikeouts':
        # No short-outing heuristic: explicit gamesStarted only.
        if rows[-1]['values'].get('pitching_games_started') not in (0, 1):
            return result, 'missing_pitcher_role'
        role = rows[-1]['values']['pitching_games_started']
        role_rows = [r for r in rows if r['values'].get('pitching_games_started') == role]
    paired = [r for r in role_rows if usage in r['values'] and
              math.isfinite(r['values'][usage]) and r['values'][usage] >= 0][-20:]
    exposure = sum(r['values'][usage] for r in paired)
    if usage and len(paired) >= 8 and exposure > 0:
        rate = sum(r['values'][stat] for r in paired)/exposure
        workload = statistics.fmean(r['values'][usage] for r in paired[-5:])
        shifted = max(mean-sigma, min(mean+sigma, .5*mean+.5*rate*workload))
        result['observed_workload_normal_v1'] = normal(shifted, sigma, line)
    return result, 'eligible'
