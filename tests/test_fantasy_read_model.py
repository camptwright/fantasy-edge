from datetime import datetime,timezone,timedelta
from sqlalchemy import text
from src.models.facts import Game
from src.services.fantasy_read_model import refresh,read,expires,revision


def candidate():
    now=datetime.now(timezone.utc)
    return {'status':'candidate','generated_at':now.isoformat(),'players':[],
            'input_timestamps':{'projections':now.isoformat()}}


async def test_background_model_is_invalidated_by_committed_source_writes(db,monkeypatch):
    from src.services import fantasy_decision_models
    async def build(*a,**k):return candidate()
    monkeypatch.setattr(fantasy_decision_models,'build',build)
    assert (await refresh(db,'test'))['status']=='refreshed'
    cached=await read(db,'test')
    assert cached['read_model']['source']=='background_checkpoint'
    # Real relevant changes still invalidate after the scoped trigger migration.
    db.add(Game(sport='nfl', season=2026, status='scheduled'))
    await db.commit()
    assert await read(db,'test') is None


async def test_rolled_back_changes_do_not_invalidate_checkpoint(db,monkeypatch):
    from src.services import fantasy_decision_models
    async def build(*a,**k):return candidate()
    monkeypatch.setattr(fantasy_decision_models,'build',build)
    await refresh(db,'test')
    before=await revision(db)
    db.add(Game(sport='nfl', season=2026, status='scheduled'))
    await db.flush()
    assert await revision(db)>before
    await db.rollback()
    assert await read(db,'test') is not None


def test_expiry_never_crosses_kickoff_or_source_staleness():
    now=datetime.now(timezone.utc)
    kickoff=now+timedelta(seconds=20)
    data={'players':[{'next_games':[{'kickoff':None},{'kickoff':kickoff.isoformat()}]}]}
    assert expires(data,now)==kickoff
    deadline=now+timedelta(seconds=10)
    assert expires({**data,'input_valid_until':deadline.isoformat()},now)==deadline
    assert expires({},now)==now+timedelta(minutes=2)
