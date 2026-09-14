"""Research-only competing Poisson scorer model; phase rates are expected counts.

An explicit other-scorer bucket prevents renormalizing only the listed players.
This is not a trained model or a bookmaker settlement implementation.
"""
import math

OTHER = '__other__'
NONE = '__none__'


def probabilities(phases):
    if len(phases) != 4:
        raise ValueError('four regulation-quarter rate maps required')
    universe = set(phases[0])
    if OTHER not in universe or NONE in universe:
        raise ValueError('explicit other scorer required; no-TD is derived')
    for phase in phases:
        if set(phase) != universe:
            raise ValueError('inconsistent selection universe')
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v < 0 for v in phase.values()):
            raise ValueError('invalid expected touchdown count')
        if not math.isfinite(sum(phase.values())):
            raise ValueError('invalid total rate')

    def ordered(sequence):
        result = dict.fromkeys(universe, 0.0)
        survival = 1.0
        for phase in sequence:
            total = sum(phase.values())
            if total:
                mass = survival * -math.expm1(-total)
                for player, rate in phase.items():
                    result[player] += mass * rate / total
                survival *= math.exp(-total)
        result[NONE] = survival
        return result

    return {'recipe': 'piecewise_competing_poisson_regulation_v1',
        'first': ordered(phases), 'last': ordered(list(reversed(phases))),
        'scope': 'regulation_only', 'serving_enabled': False,
        'requirements': ['validated_phase_rate_training', 'pregame_selection_universe',
                         'bookmaker_overtime_contract', 'prospective_joint_evaluation']}
