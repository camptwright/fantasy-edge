import pytest
from src.services.count_only_shadow import predict, RECIPE
from src.services.forecast_capture import shadow_predictions
from src.services.shadow_props import predict as existing, count_distribution, probabilities


def feature():
    return {'canonical_stat': 'rbis', 'mean': 1.2, 'variance': 2., 'games': 12,
            'recent_mean': 2.2, 'opportunity': None}


def test_frozen_formula_matches_research_variant():
    f = feature()
    candidate = predict(f, .5, 'mlb')[RECIPE]
    dist, _ = count_distribution(f['mean'], .5*f['variance']+.5*f['mean'])
    assert candidate['model_probability'] == pytest.approx(probabilities(dist, .5)['model_probability'])
    assert candidate['comparison_baseline'] == 'retained_baseline'
    assert candidate['analysis_role'] == 'primary'
    assert not candidate['automatic_deployment']


def test_recency_and_opportunity_do_not_shift_candidate():
    f = feature()
    first = predict(f, 1., 'mlb')
    f.update(recent_mean=100, opportunity={'recent_mean': 100, 'observed_rate': 10})
    assert predict(f, 1., 'mlb') == first
    p = first[RECIPE]
    assert p['over_probability']+p['under_probability']+p['push_probability'] == pytest.approx(1)


def test_scope_and_invalid_inputs():
    assert predict(feature(), .5, 'nfl') == {}
    assert predict({**feature(), 'games': 3}, .5, 'mlb') == {}
    assert predict({**feature(), 'mean': float('nan')}, .5, 'mlb') == {}
    assert predict({**feature(), 'canonical_stat': 'rbis', 'mean': 0, 'variance': 0}, 0., 'mlb') == {}


def test_existing_shadows_remain_identical():
    f = feature()
    before = existing(f, .5, 2.)
    after = shadow_predictions(f, .5, 2., 'mlb')
    assert RECIPE in after
    for key, value in before.items():
        assert {k: v for k,v in after[key].items() if k != 'recipe_version'} == value


@pytest.mark.asyncio
async def test_grading_uses_retained_not_served_baseline(tmp_path):
    import json
    import uuid
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.services.forecast_grading import grade
    now = datetime.now(timezone.utc)-timedelta(days=1)
    gid, pid = uuid.uuid4(), uuid.uuid4()
    record = {'kind': 'player', 'game_id': str(gid), 'player_id': str(pid), 'quote_id': 'q',
        'market': 'rbis', 'line': .5, 'prediction': {'model_probability': .9, 'baseline_model_probability': .2},
        'shadow_predictions': {RECIPE: {'model_probability': .7, 'recipe_version': 'test',
                                       'comparison_baseline': 'retained_baseline'}}}
    (tmp_path/'1.json').write_text(json.dumps({'schema_version': 1, 'model_version': 'model',
        'captured_at': now.isoformat(), 'records': [record]}))
    # The baseline already existed before this recipe was introduced.
    earlier = {**record, 'shadow_predictions': {}}
    (tmp_path/'0.json').write_text(json.dumps({'schema_version': 1, 'model_version': 'model',
        'captured_at': (now-timedelta(minutes=15)).isoformat(), 'records': [earlier]}))
    game = SimpleNamespace(id=gid, sport='mlb', status='final', game_time=now+timedelta(hours=1))
    fact = SimpleNamespace(player_id=pid, game_id=gid, stat_type='rbis', value=1.)
    db = AsyncMock()
    db.scalars.side_effect = [SimpleNamespace(all=lambda: [game]), SimpleNamespace(all=lambda: [fact]),
                             SimpleNamespace(all=lambda: [])]
    report = await grade(db, tmp_path)
    score = report['shadow_reports'][0]['scorecard']
    assert score['paired_baseline']['brier'] == pytest.approx(.64)
    assert score['paired_candidate']['brier'] == pytest.approx(.09)
