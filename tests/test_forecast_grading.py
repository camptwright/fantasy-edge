import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from src.services.forecast_grading import load_cohort, outcome, latest_report, grade

NOW = datetime.now(timezone.utc)


def game(**kwargs):
    return SimpleNamespace(**({'game_time': NOW+timedelta(hours=1), 'status': 'final',
        'home_score': 24, 'away_score': 20} | kwargs))


@pytest.mark.parametrize('market,side,line,expected', [
    ('moneyline', 'home', None, ('graded', 1)),
    ('moneyline', 'away', None, ('graded', 0)),
    ('spread', 'home', -4, ('push', None)),
    ('spread', 'away', 5, ('graded', 1)),
    ('total', 'over', 43.5, ('graded', 1)),
    ('total', 'under', 44.5, ('graded', 1)),
    ('first_half', 'over', 20, ('unsupported', None)),
])
def test_team_outcome(market, side, line, expected):
    assert outcome({'kind': 'team', 'market': market, 'side': side, 'line': line}, game(), {}, NOW) == expected


def test_missing_and_timing():
    record = {'kind': 'player', 'market': 'points', 'player_id': 'p', 'game_id': 'g', 'line': 20}
    assert outcome(record, game(), {}, NOW) == ('missing_result', None)
    assert outcome(record, game(), {('p', 'g', 'points'): 20}, NOW) == ('push', None)
    assert outcome(record, game(), {('p', 'g', 'points'): 21}, NOW) == ('graded', 1)
    assert outcome(record, game(status='scheduled'), {}, NOW) == ('pending', None)
    assert outcome(record, game(game_time=NOW), {}, NOW) == ('invalid_timing', None)
    assert outcome(record, game(status='cancelled'), {}, NOW) == ('needs_review', None)


def test_cohort_and_fail_closed(tmp_path):
    record = {'kind': 'team', 'game_id': str(uuid4()), 'market': 'spread', 'quote_id': 'a'}
    payload = {'schema_version': 1, 'captured_at': NOW.isoformat(), 'model_version': 'v1', 'records': [record]}
    (tmp_path/'a.json').write_text(json.dumps(payload))
    payload['captured_at'] = (NOW+timedelta(minutes=15)).isoformat()
    payload['records'] = [record | {'quote_id': 'b', 'line': 10}]
    (tmp_path/'b.json').write_text(json.dumps(payload))
    cohort, raw, files = load_cohort(tmp_path)
    assert (len(cohort), raw, files) == (1, 2, 2)
    assert next(iter(cohort.values()))[1]['quote_id'] == 'a'
    (tmp_path/'c.json').write_text('{')
    with pytest.raises(ValueError):
        load_cohort(tmp_path)


def test_report_unavailable(tmp_path):
    assert latest_report(tmp_path)['status'] == 'awaiting_grading'
    (tmp_path/'a.json').write_text('{')
    assert latest_report(tmp_path)['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_saved_probability_is_scored(tmp_path):
    from unittest.mock import AsyncMock
    gid = str(uuid4())
    record = {'kind': 'team', 'game_id': gid, 'market': 'moneyline', 'side': 'home',
              'quote_id': 'a', 'prediction': {'model_probability': .8, 'baseline_model_probability': .6}}
    payload = {'schema_version': 1, 'captured_at': NOW.isoformat(), 'model_version': 'v1', 'records': [record]}
    (tmp_path/'a.json').write_text(json.dumps(payload))
    db = AsyncMock()
    db.scalars.side_effect = [SimpleNamespace(all=lambda: [game(id=gid, sport='nfl')]),
                             SimpleNamespace(all=lambda: []), SimpleNamespace(all=lambda: [])]
    result = await grade(db, tmp_path)
    assert result['counts'] == {'graded': 1}
    assert result['reports'][0]['brier_score'] == pytest.approx(.04)
    assert result['reports'][0]['independent_games'] == 1
    assert result['reports'][0]['paired_baseline_brier'] == pytest.approx(.16)
    assert result['reports'][0]['paired_baseline_samples'] == 1
