from datetime import datetime, timedelta, timezone
import pytest
from src.services.roster_stat_model import forecast

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
def rows(n=20):
    return [dict(game_id=str(i), time=NOW-timedelta(days=30-i),
                 values={'receiving_yards': float(i*5), 'targets': float(i+1)}) for i in range(n)]

def test_minimum_and_missing_not_zero():
    assert forecast(rows(7), 'receiving_yards', NOW)['status'] == 'insufficient_history'
    assert forecast(rows(), 'receptions', NOW)['games'] == 0

def test_future_excluded_and_baseline_retained():
    history = rows()
    result = forecast(history, 'receiving_yards', NOW)
    history.append(dict(game_id='future', time=NOW, values={'receiving_yards': 9999}))
    assert forecast(history, 'receiving_yards', NOW) == result
    assert result['baseline'] == 47.5
    assert result['method'] == 'opportunity_blend'
    assert result['evaluation']['games'] == 12

def test_duplicate_rejected():
    history = rows()
    assert forecast(history+[history[0]], 'receiving_yards', NOW)['status'] == 'duplicate_history'

def test_zero_is_valid_and_nonfinite_excluded():
    history = rows(8)
    for row in history: row['values']['receptions'] = 0
    assert forecast(history, 'receptions', NOW)['baseline'] == 0
    history[0]['values']['receptions'] = float('nan')
    assert forecast(history, 'receptions', NOW)['status'] == 'insufficient_history'

def test_backtest_is_past_only():
    history = rows(9)
    result = forecast(history, 'receiving_yards', NOW)
    assert result['evaluation']['games'] == 1
    assert result['evaluation']['baseline_mae'] == pytest.approx(40-17.5)
