"""Background presentation summaries bound to their source checkpoint."""
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest


def recipe():
    from src.services.model_version import semantic_hash
    root=Path(__file__).parent
    files=[root/'workspace_background.py',root/'trade_finder.py',root/'season_sim.py',
           root/'waiver_guidance.py',root/'engine_coverage.py',root.parent/'api/routers/workspace.py']
    return digest({p.name:semantic_hash(p.read_text()) for p in files if p.exists()})


def key(league_id,kind):
    return 'workspace:'+league_id+':'+kind


async def cached(db,league_id,kind,data):
    if not isinstance(data,dict) or not isinstance(data.get('read_model'),dict):return None
    row=await db.get(DerivedCheckpoint,key(league_id,kind))
    if row is None or not isinstance(row.payload,dict) or digest(row.payload)!=row.digest:return None
    p=row.payload
    evidence=data['read_model']
    if (p.get('recipe')!=recipe() or p.get('source_generated_at')!=evidence.get('generated_at')
        or p.get('source_revision')!=evidence.get('input_revision')
        or p.get('source_model_version')!=data.get('recipe_version')
        or p.get('expires_at')!=evidence.get('expires_at')):return None
    try:
        now=datetime.now(timezone.utc)
        if not datetime.fromisoformat(p['generated_at'])<=now<datetime.fromisoformat(p['expires_at']):return None
        if not datetime.fromisoformat(evidence['generated_at'])<=now:return None
    except (TypeError,ValueError,KeyError):return None
    return p.get('data') if isinstance(p.get('data'),dict) else None


async def refresh(db,league_id):
    from src.services.workspace_checkpoints import read
    from src.api.routers.workspace import compute_standings,compute_trade_ideas
    data=await read(db,league_id)
    if data is None:return {'status':'awaiting_source_checkpoint'}
    evidence=data['read_model']
    for kind,compute in [('standings',compute_standings),('trade-ideas',compute_trade_ideas)]:
        result=await compute(league_id,db,data)
        payload={'recipe':recipe(),'source_generated_at':evidence['generated_at'],
            'source_revision':evidence['input_revision'],'source_model_version':data.get('recipe_version'),
            'generated_at':datetime.now(timezone.utc).isoformat(),
            'expires_at':evidence['expires_at'],'data':result.model_dump(mode='json')}
        values={'name':key(league_id,kind),'digest':digest(payload),'payload':payload,'updated_at':datetime.now(timezone.utc)}
        statement=insert(DerivedCheckpoint).values(**values)
        await db.execute(statement.on_conflict_do_update(index_elements=['name'],
            set_={k:getattr(statement.excluded,k) for k in values if k!='name'}))
    await db.commit()
    return {'status':'refreshed','league_id':league_id}
