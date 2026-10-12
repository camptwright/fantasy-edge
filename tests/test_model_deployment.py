import json
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from src.models.base import utcnow
from src.models.governance import ModelArtifact,ModelReviewEvidence,ModelDeployment
from src.services.model_deployment import blockers,select_model,selection
from src.services.nfl_lab_registry import artifact_version

def report(version,now):
    return {'version':version,'reviewed_at':now.isoformat(),'predictions_missing_frozen_evidence':0,'baseline_identity':'retained_serving_elo',
        'promotion_check':{'decision_not_before':(now-timedelta(days=1)).isoformat(),
        'review':{'promotion_eligible':True,'blockers':[],'independent_games':201}}}

def test_promotion_gate_fails_closed():
    now=utcnow();r=report('v',now)
    assert not blockers(r,'v',now)
    assert 'review_version_mismatch' in blockers(r,'other',now)
    assert 'stale_review' in blockers(r,'v',now+timedelta(days=2))
    assert blockers({},'v',now)
    r['promotion_check']['review']['blockers']=['market_not_beaten']
    assert 'prospective_gate_failed' in blockers(r,'v',now)

async def test_explicit_promotion_revocation_and_baseline_rollback(db,tmp_path,monkeypatch):
    from src.api.routers import nfl_predictor as router
    now=utcnow();payload={'test_artifact':True};version=artifact_version(payload)
    path=tmp_path/'model.json';path.write_text(json.dumps(payload));monkeypatch.setattr(router,'ARTIFACT',path)
    db.add(ModelArtifact(version=version,kind='independent',trained_at=now,seasons_used=[2025],
        artifact_path=str(path),artifact_payload=payload,passed_gate=False))
    await db.flush()
    db.add(ModelReviewEvidence(artifact_version=version,report=report(version,now),created_at=now))
    await db.commit()
    assert (await selection(db,now))['status']=='retained_baseline'
    assert (await select_model(db,version,actor='test',reason='unit-test qualified evidence',now=now))['status']=='promoted'
    assert (await selection(db,now))['status']=='approved'
    assert (await selection(db,now+timedelta(days=2)))['status']=='retained_baseline'
    failed=report(version,now+timedelta(seconds=1))
    failed['promotion_check']['review']['promotion_eligible']=False
    db.add(ModelReviewEvidence(artifact_version=version,report=failed,created_at=now+timedelta(seconds=1)))
    await db.commit()
    assert (await selection(db,now+timedelta(seconds=2)))['status']=='retained_baseline'
    with pytest.raises(ValueError,match='Promotion refused'):
        await select_model(db,version,actor='test',reason='not allowed',now=now+timedelta(seconds=2))
    await db.rollback()
    assert (await select_model(db,None,actor='test',reason='rollback',now=now+timedelta(seconds=3)))['status']=='baseline_restored'
    assert await db.scalar(select(func.count()).select_from(ModelDeployment))==2
