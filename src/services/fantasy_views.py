"""Compatibility views of the single fantasy decision source."""
from fastapi import HTTPException
from src.services.fantasy_request_models import build
from src.services.fantasy_decision_models import optimize
from datetime import datetime, timezone
from pathlib import Path
from config.settings import get_settings
from starlette.concurrency import run_in_threadpool
from src.services.news_evidence import headlines_for_players


async def data_for(db, league_id):
    data=await build(db,league_id)
    if data.get('status')!='candidate':
        raise HTTPException(409, data.get('status','missing_inputs'))
    return data


def player_view(p):
    return {**p,'projected_points':p['decision_points'],
        'custom_projected_points':None,'projection_tier':p['decision_tier'],
        'opponent':p.get('opponent'),'news':p.get('news',[]),
        'news_status':p.get('news_status','not_loaded')}


async def recommendations(db, league_id):
    data=await data_for(db,league_id)
    mine=[p for p in data['players'] if p['is_mine']]
    lineup=data['lineup_decision']
    open_window=lineup['status']=='lock_preserving_candidate'
    by_id={p['player_id']:p for p in data['players']}
    # Name-matched headlines are context, never structured availability or
    # numeric adjustments. Bound work to displayed roster/waiver players.
    displayed={p['player_id']:p['name'] for p in mine}
    displayed.update({m['add_id']:by_id[m['add_id']]['name'] for m in data['waivers']['moves']})
    news=await run_in_threadpool(headlines_for_players,Path(get_settings().raw_archive_dir)/'news',
                                displayed,datetime.now(timezone.utc))
    for pid in displayed:
        by_id[pid]['news']=news.get(pid,[])
        by_id[pid]['news_status']='name_matched_headline_context_only' if news.get(pid) else 'no_recent_matched_headlines'
    selected={p['player_id'] for p in lineup['lineup']}
    return {'league_id':league_id,'week':data['week'],'planning_week':data['planning_week'],
        'roster_positions':data['roster_positions'],
        'starting_lineup':[{'slot':p['slot'],'player':player_view(by_id[p['player_id']]) if p['player_id'] else None} for p in lineup['lineup']],
        'bench':[player_view(p) for p in mine if p['player_id'] not in selected],
        'waivers':[{**player_view(by_id[m['add_id']]),'recommended':True,
            'drop_candidate':player_view(by_id[m['drop_id']]),'lineup_gain':m['lineup_gain']}
            for m in data['waivers']['moves']],
        'lineup_suggestions':[], 'projection_status':'estimated' if open_window else 'ranked_only',
        'projection_source':'Shared fantasy decision engine', 'projection_records':sum(p['decision_points'] is not None for p in mine),
        'notes':data['notes']+['Provider estimates are not validated models. Unknown values stay null.',
            'Headlines are recent name-matched context, not verified injury facts or numeric adjustments. No headline is not evidence that a player is healthy.',
            'Locked starters remain in their exact slots; only unstarted slots can change. No remaining-points total is inferred.'],
        'rows':[player_view(p) for p in mine if p['decision_points'] is not None], 'headlines':[],
        'coverage':data['coverage'],'lineup_simulation':data['lineup_simulation']}


async def matchup(db, league_id):
    data=await data_for(db,league_id)
    if not data['matchup_rosters'].get('mine'):
        raise HTTPException(409,'Platform matchup is not available for this week')
    by_id={p['player_id']:p for p in data['players']}
    def side(raw, mine=False):
        if not raw:return None
        ids=list(map(str,raw.get('starters',[])))
        roster=next((r for r in data['rosters'] if r['roster_id']==raw.get('roster_id')),{})
        def views(ids):
            return [player_view(by_id[pid]) if pid in by_id else {
                'player_id':pid, 'name':f'Unresolved starter ({pid})',
                'position':None, 'team':None, 'projected_points':None,
                'custom_projected_points':None, 'projection_tier':'ranked_only',
                'decision_source':'unresolved_player_identity',
            } for pid in map(str, ids)]
        values=[by_id.get(pid,{}).get('decision_points') for pid in ids]
        return {'roster_id':raw.get('roster_id'),'starters':views(ids),
            'bench':views([pid for pid in roster.get('player_ids',[]) if pid not in ids]),
            'points':raw.get('points'),
            'projection_coverage':{'available':sum(v is not None for v in values),'total':len(ids)},
            'projected_points':sum(values) if values and all(v is not None for v in values) else None}
    return {'league_id':league_id,'week':data['week'],
        'your_roster':side(data['matchup_rosters']['mine']), 'opponent':side(data['matchup_rosters']['opponent']),
        'decision_status':data['matchup']['status'],'lineup_simulation':data['lineup_simulation']}
