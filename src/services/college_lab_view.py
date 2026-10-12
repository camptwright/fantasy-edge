"""Bounded display projection; never changes research, captures or evidence."""


def compact(report, *, team=None, offset=0, limit=50):
    players=report.get('players',[])
    teams=sorted({p['team'] for p in players})
    selected=team if team is not None else ('Texas Longhorns' if 'Texas Longhorns' in teams else next(iter(teams),None))
    rows=sorted((p for p in players if p['team']==selected),key=lambda p:(p.get('name',''),p['player_id']))
    offset=max(0,offset);limit=max(1,min(limit,100))
    return {**report,'players':rows[offset:offset+limit], 'teams':teams,'selected_team':selected,
            'pagination':{'offset':offset,'limit':limit,'total':len(rows),
                          'all_players':len(players),'next_offset':offset+limit if offset+limit<len(rows) else None},
            'view_scope':'Selected team and player page only; coverage and evaluation metrics retain their full-cohort meaning.'}
