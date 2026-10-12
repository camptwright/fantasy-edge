"""Explicit NFL moneyline deployment. All failed gates retain the baseline."""
from datetime import datetime,timedelta
from sqlalchemy import select,text
from src.models.base import utcnow
from src.models.governance import ModelArtifact,ModelReviewEvidence,ModelDeployment

SCOPE='nfl:moneyline'

def blockers(report,version,now):
    reasons=[]
    if report.get('version')!=version:reasons.append('review_version_mismatch')
    if report.get('baseline_identity')!='retained_serving_elo':reasons.append('wrong_baseline_comparator')
    try:
        reviewed=datetime.fromisoformat(report['reviewed_at'])
        if not now-timedelta(hours=24)<=reviewed<=now:reasons.append('stale_review')
    except (KeyError,ValueError,TypeError):reasons.append('invalid_review_timestamp')
    card=report.get('promotion_check',{});review=card.get('review',{})
    if review.get('promotion_eligible') is not True or review.get('blockers')!=[]:reasons.append('prospective_gate_failed')
    if review.get('independent_games',0)<200:reasons.append('insufficient_independent_games')
    if report.get('predictions_missing_frozen_evidence')!=0:reasons.append('incomplete_evidence')
    try:
        if card.get('decision_not_before') is None and (card.get('protocol') or {}).get('collection_mode')=='fixed_sample':
            reasons.append('awaiting_fixed_sample')
        elif datetime.fromisoformat(card['decision_not_before'])>now:reasons.append('evaluation_window_open')
    except (KeyError,ValueError,TypeError):reasons.append('invalid_evaluation_window')
    return reasons


async def latest_review(db,version):
    return await db.scalar(select(ModelReviewEvidence).where(ModelReviewEvidence.artifact_version==version)
        .order_by(ModelReviewEvidence.created_at.desc(),ModelReviewEvidence.id.desc()).limit(1))


async def select_model(db,version,*,actor,reason,now=None):
    """Null version is rollback; a version is explicit promotion, never override."""
    if not actor.strip() or not reason.strip():raise ValueError('Actor and reason are required')
    if len(actor)>128:raise ValueError('Actor exceeds 128 characters')
    now=now or utcnow()
    await db.execute(text('SELECT pg_advisory_xact_lock(78241905)'))
    evidence=None
    if version is not None:
        from src.api.routers.nfl_predictor import ARTIFACT
        from src.services.nfl_lab_registry import artifact_version
        import json
        current=json.loads(ARTIFACT.read_text())
        if artifact_version(current)!=version:raise ValueError('Only the current executable artifact can be promoted')
        artifact=await db.scalar(select(ModelArtifact).where(ModelArtifact.version==version))
        if artifact is None or artifact.artifact_payload!=current:raise ValueError('Artifact evidence missing or mismatched')
        evidence=await latest_review(db,version)
        reasons=blockers(evidence.report,version,now) if evidence else ['missing_review']
        if reasons:raise ValueError('Promotion refused: '+', '.join(reasons))
        artifact.passed_gate=True
    decision=ModelDeployment(scope=SCOPE,artifact_version=version,review_id=evidence.id if evidence else None,
        actor=actor,reason=reason,created_at=now)
    db.add(decision);await db.commit()
    return {'decision_id':str(decision.id),'scope':SCOPE,'version':version,'status':'promoted' if version else 'baseline_restored'}


async def selection(db,now=None):
    now=now or utcnow()
    decision=await db.scalar(select(ModelDeployment).where(ModelDeployment.scope==SCOPE)
        .order_by(ModelDeployment.created_at.desc(),ModelDeployment.id.desc()).limit(1))
    baseline={'status':'retained_baseline','version':None,'blockers':[]}
    if decision is None or decision.artifact_version is None:return baseline
    version=decision.artifact_version
    evidence=await latest_review(db,version)
    reasons=blockers(evidence.report,version,now) if evidence else ['missing_review']
    from src.api.routers.nfl_predictor import ARTIFACT
    from src.services.nfl_lab_registry import artifact_version
    import json
    try:
        current=json.loads(ARTIFACT.read_text())
        if artifact_version(current)!=version:reasons.append('executable_version_mismatch')
        artifact=await db.scalar(select(ModelArtifact).where(ModelArtifact.version==version))
        if artifact is None or artifact.artifact_payload!=current:reasons.append('artifact_evidence_mismatch')
        elif artifact.passed_gate is not True:reasons.append('artifact_not_approved')
    except (OSError,ValueError):reasons.append('artifact_unavailable')
    if reasons:return {**baseline,'blockers':reasons}
    return {'status':'approved','version':version,'blockers':[],'decision_id':str(decision.id),
        'evaluated_at':evidence.report['reviewed_at']}


async def forecasts(db):
    selected=await selection(db)
    if selected['status']!='approved':return {},selected
    from src.api.routers.nfl_predictor import nfl_predictor
    predictions=await nfl_predictor(db)
    import math
    rows={r['id']:r for r in predictions['games'] if r.get('status')=='experimental' and r.get('venue_verified') and r.get('market_reference')
        and isinstance(r.get('home_probability'),(float,int)) and math.isfinite(r['home_probability']) and 0<=r['home_probability']<=1}
    # Recheck after inference so a concurrent operator rollback takes effect.
    final=await selection(db)
    return (rows,final) if final==selected else ({},final)
