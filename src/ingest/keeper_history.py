"""Daily, exact-draft keeper evidence. Null keeper flags remain unknown."""
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from src.models.sleeper import SleeperLeagueSnapshot
from src.services.keeper_rules import LEAGUE_ID


def validate(league, draft, picks):
    if (not isinstance(draft,dict) or str(draft.get('draft_id'))!=str(league.get('draft_id'))
        or str(draft.get('league_id'))!=str(league['league_id'])
        or str(draft.get('season'))!=str(league['season'])
        or draft.get('sport')!='nfl' or draft.get('status')!='complete'
        or not isinstance(picks,list) or not picks):
        raise ValueError('unverified completed draft')
    ids=set(); positions=set()
    for p in picks:
        if (not isinstance(p,dict) or not p.get('player_id') or
            str(p.get('draft_id'))!=str(draft['draft_id']) or
            type(p.get('round')) is not int or p['round']<1 or
            type(p.get('pick_no')) is not int or p['pick_no']<1 or
            not str(p.get('roster_id','')).isdigit()):
            raise ValueError('invalid draft pick')
        if p['player_id'] in ids or p['pick_no'] in positions:
            raise ValueError('ambiguous draft picks')
        ids.add(p['player_id']);positions.add(p['pick_no'])
    return {'league_id':league['league_id'],'season':str(league['season']),
            'draft_id':draft['draft_id'],'draft':draft,'picks':picks}


async def collect(db,client,league):
    if league['league_id']!=LEAGUE_ID:return {'status':'not_configured'}
    prior=await db.scalar(select(SleeperLeagueSnapshot).where(
        SleeperLeagueSnapshot.league_id==LEAGUE_ID,
        SleeperLeagueSnapshot.week==0,SleeperLeagueSnapshot.kind=='keeper_draft'))
    now=datetime.now(timezone.utc)
    if (prior and prior.payload.get('draft_id')==league.get('draft_id')
        and prior.payload.get('season')==str(league['season'])
        and 0<=(now-prior.synced_at).total_seconds()<86400):
        return {'status':'cached'}
    draft_id=str(league.get('draft_id') or '')
    if not draft_id.isdigit():raise ValueError('missing draft identity')
    response=await client.get(f'/draft/{draft_id}');response.raise_for_status()
    picks=await client.get(f'/draft/{draft_id}/picks');picks.raise_for_status()
    evidence=validate(league,response.json(),picks.json())
    from src.scheduler.calibration import archive
    from src.ingest.sleeper import _snapshot
    evidence={**evidence,'observed_at':now.isoformat()}
    path=archive('keeper-draft-history',evidence)
    await _snapshot(db,LEAGUE_ID,0,'keeper_draft',{**evidence,'archive':Path(path).name})
    return {'status':'collected','picks':len(evidence['picks'])}


def player_evidence(payload,player_id,roster_id):
    picks=[p for p in payload.get('picks',[]) if str(p.get('player_id'))==str(player_id)]
    if len(picks)!=1:return {'status':'missing_or_ambiguous_draft_pick'}
    p=picks[0]
    return {'status':'archived_draft_pick','draft_round':p['round'],
        'draft_roster_id':str(p['roster_id']),
        'same_draft_roster':str(p['roster_id'])==str(roster_id),
        'kept_in_draft_season':p.get('is_keeper') if type(p.get('is_keeper')) is bool else None,
        'draft_season':payload['season'],'draft_id':payload['draft_id'],
        'observed_at':payload.get('observed_at'),'archive':payload.get('archive'),
        'scope':'Draft evidence only. Same roster does not prove continuous ownership; future cost-pick availability is not inferred.'}
