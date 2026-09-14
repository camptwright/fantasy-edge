import math
import pytest
from src.services.joint_scorer_shadow import probabilities


def test_mass_includes_other_and_no_touchdown():
    result = probabilities([{'a': .2, 'b': .1, '__other__': .1}]*4)
    for which in ('first', 'last'):
        assert sum(result[which].values()) == pytest.approx(1)
        assert result[which]['__none__'] == pytest.approx(math.exp(-1.6))
        assert result[which]['a'] == pytest.approx(2*result[which]['b'])
    assert not result['serving_enabled']


def test_early_vs_late_scorer_are_distinct():
    result = probabilities([{'a': 1, 'b': 0, '__other__': 0}]*2 + [{'a': 0, 'b': 1, '__other__': 0}]*2)
    assert result['first']['a'] > result['first']['b']
    assert result['last']['b'] > result['last']['a']


def test_zero_rates_mean_no_touchdown():
    assert probabilities([{'a': 0, '__other__': 0}]*4)['first']['__none__'] == 1


@pytest.mark.parametrize('phase', [{'a': 1}, {'a': -1, '__other__': 0},
    {'a': float('nan'), '__other__': 0}, {'a': True, '__other__': 0}])
def test_invalid_rates_or_missing_other_fail_closed(phase):
    with pytest.raises(ValueError):
        probabilities([phase]*4)
