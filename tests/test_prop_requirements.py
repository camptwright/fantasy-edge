import pytest
from src.services.prop_requirements import requirement


@pytest.mark.parametrize('stat,expected', [
    ('passing_yards', None), ('fumbles_lost', None), ('rush_rec_yards', None),
    ('fantasy_points', 'requires_settlement_rules'), ('total_tds', 'requires_settlement_rules'),
    ('1h_receptions', 'requires_period_model'), ('1q_passing_yards', 'requires_period_model'),
    ('25_rec_yards_in_each_half', 'requires_period_model'),
    ('first_td_scorer', 'requires_play_order_model'),
    ('game_high_rec_yards', 'requires_comparative_model')])
def test_special_markets_require_explicit_models(stat, expected):
    assert requirement(stat) == expected
