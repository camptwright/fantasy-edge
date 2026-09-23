"""Compatibility views of the single fantasy decision source."""
from fastapi import HTTPException
from src.services.fantasy_decision_models import build, optimize


async def data_for(db, league_id):
    data=await build(db,league_id)
    if data.get('status')!='candidate':
        raise HTTPException(409, data.get('status','missing_inputs'))
    return data


def player_view(p):
    return {**p,'projected_points':p['decision_points'],
        'custom_projected_points':None,'projection_tier':p['decision_tier'],
        'opponent':None,'news':[]}


async def recommendations(db, league_id):
    data=await data_for(db,league_id)
    mine=[p for p in data['players'] if p['is_mine']]
    lineup=data['lineup_decision']
    open_window=lineup['status']=='lock_preserving_candidate'
    by_id={p['player_id']:p for p in data['players']}
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
            return [player_view(by_id[pid]) for pid in ids if pid in by_id]
        values=[by_id.get(pid,{}).get('decision_points') for pid in ids]
        return {'roster_id':raw.get('roster_id'),'starters':views(ids),
            'bench':views([pid for pid in roster.get('player_ids',[]) if pid not in ids]),
            'points':raw.get('points',0),'projected_points':sum(values) if values and all(v is not None for v in values) else None}
    return {'league_id':league_id,'week':data['week'],
        'your_roster':side(data['matchup_rosters']['mine']), 'opponent':side(data['matchup_rosters']['opponent']),
        'decision_status':data['matchup']['status'],'lineup_simulation':data['lineup_simulation']}
