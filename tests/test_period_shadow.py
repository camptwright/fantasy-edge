from datetime import datetime, timezone
import hashlib
import pytest
from src.services.period_shadow import predict
from src.services.settlement_binding import bind

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def test_provider_period_receiving_alias_is_captured():
    from src.services.period_shadow_capture import history_market,MARKETS
    assert '1h_rec_yards' in MARKETS
    assert history_market('1h_rec_yards')=='1h_receiving_yards'
    assert history_market('1q_rushing_attempts')=='1q_carries'


def history():
    return [{'game_id': str(i), 'date': f'2025-09-{i+1:02}',
             'available_at': '2026-09-10T00:00:00+00:00',
             'labels': [{'player_id': 'p', 'market': '1h_receptions', 'value': i%3}]} for i in range(8)]


def test_probability_mass_includes_push_only_at_integer_lines():
    for line in (1, 1.5):
        r = predict(history(), 'p', '1h_receptions', line, NOW)
        assert abs(r['over'] + r['under'] + r['push'] - 1) < 1e-10
        assert (r['push'] > 0) == (line == 1)


def test_future_publication_and_duplicate_games_are_rejected():
    h = history()
    h[0]['available_at'] = '2026-09-12T00:00:00+00:00'
    assert predict(h, 'p', '1h_receptions', 1.5, NOW)['status'] == 'insufficient_published_history'
    h = history(); h[0]['game_id'] = h[1]['game_id']
    assert predict(h, 'p', '1h_receptions', 1.5, NOW)['status'] == 'duplicate_history_game'


def test_scorer_not_treated_as_independent_period_model():
    assert predict(history(), 'p', 'first_td_scorer', .5, NOW)['status'] == 'requires_joint_scorer_model'


def test_missing_product_or_jurisdiction_does_not_bind():
    result = bind({'book': 'bovada', 'market': '1h_receptions', 'quote_id': 'q', 'captured_at': NOW.isoformat()})
    assert not result['ready']
    assert {'missing_product', 'missing_jurisdiction'} <= set(result['blockers'])


def test_rules_bound_to_exact_identity_and_effective_interval():
    q = {'book': 'bovada', 'product': 'standard', 'jurisdiction': 'X', 'sport': 'nfl', 'market': '1h_receptions',
         'quote_id': 'q', 'captured_at': NOW.isoformat()}
    source = b'Verified test fixture rules'
    rule = {**q, 'status': 'verified', 'source': 'https://example.test/rules',
            'source_sha256': hashlib.sha256(source).hexdigest(),
            'source_observed_at': '2026-01-01T00:00:00+00:00',
            'clauses': dict.fromkeys(('stat_definition', 'participation', 'overtime', 'void_conditions', 'push_treatment', 'period_definition', 'period_completion'), 'test'),
            'effective_from': '2026-01-01T00:00:00+00:00', 'effective_until': '2026-10-01T00:00:00+00:00'}
    result = bind(q, rule, source_snapshot=source)
    assert result['ready']
    assert not bind(q, {**rule, 'source_observed_at': '2027-01-01T00:00:00+00:00'}, source_snapshot=source)['ready']
    assert not bind(q, {**rule, 'clauses': {k:v for k,v in rule['clauses'].items() if k!='period_completion'}}, source_snapshot=source)['ready']
    assert not bind(q, rule)['ready']
    assert not bind(q, rule, source_snapshot=b'changed')['ready']
    rule['product'] = 'builder'
    assert not bind(q, rule, source_snapshot=source)['ready']
    assert result['rule_contract']['product'] == 'standard'
    rule['product'] = 'standard'; rule['effective_until'] = '2026-09-01T00:00:00+00:00'
    assert not bind(q, rule, source_snapshot=source)['ready']


@pytest.mark.parametrize('value', [True, 1.5, float('nan'), float('inf')])
def test_corrupt_history_cannot_lose_probability_mass(value):
    h = history(); h[0]['labels'][0]['value'] = value
    assert predict(h, 'p', '1h_receptions', 1.5, NOW)['status'] == 'invalid_history_outcome'
