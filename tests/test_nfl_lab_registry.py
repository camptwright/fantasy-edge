from src.services.nfl_lab_registry import artifact_version
from datetime import timedelta
from unittest.mock import AsyncMock
import json
import pytest
from sqlalchemy import select,func
from src.models.base import utcnow
from src.models.facts import Game
from src.models.governance import ModelArtifact,ModelPrediction,ModelReviewEvidence
from src.services.nfl_lab_registry import execute,persist_forecast


def test_artifact_version_binds_coefficients_and_training_evidence():
    artifact={'model':{'coef':[1]},'history_hash':'a'}
    assert len(artifact_version(artifact))==64
    assert artifact_version(artifact)==artifact_version(dict(reversed(list(artifact.items()))))
    assert artifact_version(artifact)!=artifact_version({**artifact,'history_hash':'b'})


async def test_durable_review_survives_missing_forecast_archive(db,tmp_path,monkeypatch):
    from src.api.routers import nfl_predictor as router
    from src.services import nfl_lab_registry as registry
    now=utcnow()
    artifact={'trained_at':now.isoformat(),'first_season':2025,'last_season':2025,
        'evaluation':{'candidate':{'brier':.22,'log_loss':.65}}}
    artifact_path=tmp_path/'artifact.json'
    artifact_path.write_text(json.dumps(artifact))
    monkeypatch.setattr(router,'ARTIFACT',artifact_path)
    monkeypatch.setattr(registry,'get_settings',lambda:type('Settings',(),{'raw_archive_dir':str(tmp_path/'raw')})())
    game=Game(sport='nfl',season=2026,status='scheduled',game_time=now+timedelta(hours=24))
    db.add(game);await db.flush()
    monkeypatch.setattr(router,'nfl_predictor',AsyncMock(return_value={'games':[{
        'id':str(game.id),'status':'experimental','venue_verified':True,'home':'A','away':'B',
        'home_probability':.6,'baseline_home_probability':.55}]}))
    monkeypatch.setattr(registry,'market_reference',AsyncMock(return_value={'probability':.52,'quote_ids':['a','b']}))
    from src.services import nfl_epa_feed
    monkeypatch.setattr(nfl_epa_feed,'latest_features',lambda *args:{'status':'missing'})
    first=await execute(db)
    assert first['captured']==1
    prediction=await db.scalar(select(ModelPrediction))
    assert prediction.evidence['blend_25_probability']==pytest.approx(.58)
    # Simulate loss of the secondary archive, not a production deletion.
    for path in (tmp_path/'raw'/'nfl-lab-prospective'/'forecasts').glob('*.json'):
        path.unlink()
    second=await execute(db)
    assert second['forecast_count']==1 and second['captured']==0
    assert await db.scalar(select(func.count()).select_from(ModelPrediction))==1
    assert await db.scalar(select(func.count()).select_from(ModelReviewEvidence))==2
    assert (await db.scalar(select(ModelArtifact))).artifact_payload==artifact
    assert second['serving_promoted'] is False
    assert second['market_blend_25_retained_baseline_review']['review']['promotion_eligible'] is False
    governance=await router.nfl_governance(db)
    assert governance['artifact_payload_persisted'] is True
    assert governance['review']['version']==first['version']
    artifact_path.write_text(json.dumps({**artifact,'changed':True}))
    assert (await router.nfl_governance(db))['status']=='awaiting_durable_review'
    with pytest.raises(ValueError,match='cannot be overwritten'):
        await persist_forecast(db,{**prediction.evidence,'baseline':.99},first['version'])
