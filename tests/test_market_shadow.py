from copy import deepcopy
from datetime import datetime, timedelta, timezone

from src.services.market_shadow import forecasts


def slate(now):
    return [{'id': str(i), 'source': source, 'actionable': True,
        'last_seen_at': now.isoformat(), 'game_time': (now+timedelta(hours=1)).isoformat(),
        'player_id': 'p', 'game_id': 'g', 'sport': 'nfl', 'stat_type': 'passing_yards',
        'line': 200.5, 'over_price_american': -110, 'under_price_american': -110,
        'baseline_model_probability': .7}
        for i, source in enumerate(('theodds_fanduel', 'sgo_bovada', 'parlay_draftkings'))]


def test_fixed_blend_keeps_original_unchanged_and_excludes_target_book():
    now = datetime.now(timezone.utc)
    rows = slate(now)
    before = deepcopy(rows)
    result = forecasts(rows, now)
    assert len(result) == 3
    candidate = result['0']['market_blend_25_v1']
    assert abs(candidate['model_probability']-.65) < 1e-12
    assert candidate['reference_books'] == ['bovada', 'draftkings']
    assert '0' not in candidate['reference_quote_ids']
    assert candidate['serving_enabled'] is False
    assert rows == before


def test_mismatched_line_stale_dfs_and_unpaired_quotes_do_not_enter_consensus():
    now = datetime.now(timezone.utc)
    for field, value in [('line', 201.5), ('source', 'underdog'),
                         ('last_seen_at', (now-timedelta(minutes=16)).isoformat()),
                         ('under_price_american', None), ('actionable', False)]:
        rows = slate(now)
        rows[2][field] = value
        assert '0' not in forecasts(rows, now)


def test_repeated_book_does_not_masquerade_as_two_reference_books():
    now = datetime.now(timezone.utc)
    rows = slate(now)
    rows[2]['source'] = rows[1]['source']
    assert forecasts(rows, now) == {}
