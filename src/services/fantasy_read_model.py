"""Persisted fantasy read models, invalidated transactionally by source writes.

Only default roster/replacement requests are cached. Arbitrary catalog/trade
requests keep the bounded on-demand path. No expired decisions are served.
"""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from sqlalchemy import select,text
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest


def recipe():
    from src.services.model_version import semantic_hash
    root=Path(__file__).parent
    files=list(root.glob('fantasy_*.py'))+[root/'roster_stat_model.py',root/'player_identity.py',
                                          root/'result_eligibility.py',root/'lab_availability.py',
                                          root/'injury_evidence.py']
    codes={p.name:semantic_hash(p.read_text()) for p in files}
    mapping=root.parents[1]/'config/nfl_player_lab_ids.json'
    codes['identity_mapping']=mapping.read_text() if mapping.exists() else None
    return digest(codes)


async def revision(db):
    return await db.scalar(text('SELECT revision FROM fantasy_input_revision WHERE id=1'))


def expires(data,now):
    deadlines=[now+timedelta(minutes=2)]
    for stamp in data.get('input_timestamps',{}).values():
        at=datetime.fromisoformat(stamp)+timedelta(hours=6)
        if at>now:deadlines.append(at)
    for player in data.get('players',[]):
        observed=player.get('game_availability',{}).get('observed_at')
        if observed:
            deadline=datetime.fromisoformat(observed)+timedelta(hours=1)
            if deadline>now:deadlines.append(deadline)
        for game in player.get('next_games',[]):
            if game.get('kickoff'):
                at=datetime.fromisoformat(game['kickoff'])
                if at>now:deadlines.append(at)
    if data.get('input_valid_until'):
        deadlines.append(datetime.fromisoformat(data['input_valid_until']))
    return min(deadlines)


async def read(db,league_id):
    # One SQL statement binds the checkpoint and current committed revision.
    row=(await db.execute(select(DerivedCheckpoint,
        text('(SELECT revision FROM fantasy_input_revision WHERE id=1) AS source_revision'))
        .where(DerivedCheckpoint.name=='fantasy:'+league_id))).first()
    if not row:return None
    cache,current=row
    p=cache.payload
    if p.get('revision')!=current or p.get('recipe')!=recipe():return None
    if digest(p)!=cache.digest:return None
    now=datetime.now(timezone.utc)
    if not datetime.fromisoformat(p['generated_at'])<=now<datetime.fromisoformat(p['expires_at']):return None
    return {**p['data'],'read_model':{'source':'background_checkpoint','generated_at':p['generated_at'],
                                    'expires_at':p['expires_at'],'input_revision':current}}


async def refresh(db,league_id):
    from src.services.fantasy_decision_models import build
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
    version=await revision(db)
    implementation=recipe()
    data=await build(db,league_id)
    if data.get('status')!='candidate':return {'status':data.get('status','unavailable')}
    at=datetime.fromisoformat(data['generated_at'])
    payload={'revision':version,'recipe':implementation,'generated_at':at.isoformat(),
             'expires_at':expires(data,at).isoformat(),'data':data}
    values={'name':'fantasy:'+league_id,'digest':digest(payload),'payload':payload,
            'updated_at':datetime.now(timezone.utc)}
    statement=insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(index_elements=['name'],
        set_={k:getattr(statement.excluded,k) for k in values if k!='name'}))
    await db.commit()
    return {'status':'refreshed','league_id':league_id,'input_revision':version}
