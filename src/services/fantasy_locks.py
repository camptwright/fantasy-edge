"""Preserve platform lineup locks; never interpret full-week points as remaining."""
from src.services.fantasy_decision_models import optimize, FLEX, RESERVE
from src.services.roster_stat_model import finite


def lineup(players, slots, starters):
    slots=[s for s in slots if s not in RESERVE]
    by_id={p['player_id']:p for p in players}
    starters=list(map(str,starters))
    base={'status':'withheld','total':None,'unlocked_points':None,'lineup':[]}
    if len(starters)!=len(slots) or len(set(starters))!=len(starters):
        return {**base,'reason':'missing_or_duplicate_platform_starters'}
    fixed={}
    for i,pid in enumerate(starters):
        p=by_id.get(pid)
        if p is None or p.get('position') not in FLEX.get(slots[i],{slots[i]}):
            return {**base,'reason':'unknown_or_incompatible_platform_starter'}
        if p.get('locked',True):
            fixed[i]={'slot':slots[i],'player_id':pid,'name':p['name'],'points':None,'locked':True}
    pool=[p for p in players if not p.get('locked',True) and finite(p.get('decision_points'))
        and str(p.get('injury_status') or '').strip().upper() not in ('OUT','IR','DOUBTFUL','SUSPENDED','PUP')
        and not p.get('game_availability',{}).get('hold_recommendation')]
    open_indices=[i for i in range(len(slots)) if i not in fixed]
    if not open_indices:
        return {**base,'status':'all_slots_locked','lineup':[fixed[i] for i in range(len(slots))],
                'unlocked_points':0,'reason':'No remaining lineup decisions.'}
    result=optimize(pool,[slots[i] for i in open_indices],key='decision_points')
    picks={**fixed,**{i:{**p,'locked':False} for i,p in zip(open_indices,result['lineup'])}}
    return {'status':'lock_preserving_candidate' if result['total'] is not None else 'incomplete',
        'total':result['total'] if not fixed else None,'unlocked_points':result['total'],
        'lineup':[picks[i] for i in range(len(slots))], 'locked_count':len(fixed),
        'reason':'Only unstarted slots optimized; no live remaining-points or full-lineup total inferred.'}


def waivers(mine, free, slots, starters):
    before=lineup(mine,slots,starters)
    if before['unlocked_points'] is None:
        return {'status':before['status'],'before':before,'moves':[]}
    moves=[]
    for add in free:
        if add.get('locked',True) or not finite(add.get('decision_points')):continue
        alternatives=[]
        for drop in sorted(mine,key=lambda p:str(p['player_id'])):
            if drop['player_id'] in starters or drop.get('locked',True):continue
            after=lineup([p for p in mine if p['player_id']!=drop['player_id']]+[add],slots,starters)
            if after['unlocked_points'] is None:continue
            gain=round(after['unlocked_points']-before['unlocked_points'],2)
            if gain>0:
                alternatives.append({'add_id':add['player_id'],'add':add['name'],'drop_id':drop['player_id'],
                    'drop':drop['name'],'lineup_gain':gain,'after_total':after['total'],
                    'after_lineup':after['lineup'],'scope':'unstarted_slots_only'})
        if alternatives:
            alternatives.sort(key=lambda m:(-m['lineup_gain'],str(m['drop_id'])))
            best=alternatives[0]
            tied=[m for m in alternatives if m['lineup_gain']==best['lineup_gain']]
            moves.append({**best,'equivalent_drop_ids':[m['drop_id'] for m in tied],
                'drop_selection':'stable_id_not_retention_value',
                'drop_decision_status':'unresolved_retention_cost'})
    return {'status':'lock_preserving_candidate','before':before,
            'moves':sorted(moves,key=lambda m:(-m['lineup_gain'],m['add_id']))[:15]}
