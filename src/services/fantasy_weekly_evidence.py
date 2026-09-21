"""Freeze and grade provider weekly forecasts, including rookies/K/DST.

Separate cohort from the retained history model; never extrapolate weekly to ROS.
"""
import hashlib
import json
from datetime import datetime,timedelta
from src.services.roster_stat_model import finite


def candidates(lab,now):
    out=[]
    if lab.get('status')!='candidate' or lab['coverage']['stale_inputs']:return out
    for p in lab['players']:
        e=p.get('weekly_evidence',{})
        if e.get('status')!='pregame_provider_projection' or not finite(e.get('points')):continue
        games=[g for g in p['next_games'] if g.get('week')==e['week']]
        if len(games)!=1 or not games[0]['kickoff']:continue
        g=games[0];kickoff=datetime.fromisoformat(g['kickoff'])
        observed=datetime.fromisoformat(e['observed_at'])
        if not observed<=now<kickoff or not timedelta(minutes=5)<kickoff-now<=timedelta(hours=72):continue
        scoring_hash=hashlib.sha256(json.dumps(lab['scoring_settings'],sort_keys=True).encode()).hexdigest()
        identity=f"provider_weekly_v1:{lab['league_id']}:{g['id']}:{p['player_id']}:{scoring_hash}"
        out.append({'id':hashlib.sha256(identity.encode()).hexdigest(),'recipe':'provider_weekly_v1',
            'league_id':lab['league_id'],'game_id':g['id'],'week':e['week'],'player_id':p['player_id'],
            'position':p['position'],'captured_at':now.isoformat(),'kickoff':g['kickoff'],
            'scoring_hash':scoring_hash,'prediction':e,'serving_promoted':False})
    return out


def grade(record,game,snapshot):
    base={'id':record['id'],'league_id':record['league_id'],'position':record['position']}
    if game is None or game.status!='final':return {**base,'status':'awaiting_final'}
    at=datetime.fromisoformat(record['captured_at'])
    if not game.game_time or at>=game.game_time:return {**base,'status':'invalid_capture_time'}
    if snapshot is None or snapshot.synced_at<game.game_time+timedelta(hours=24) or not isinstance(snapshot.payload,list):return {**base,'status':'missing_final_platform_points'}
    values=[r.get('players_points',{}).get(record['player_id']) for r in snapshot.payload if record['player_id'] in r.get('players_points',{})]
    if not values or not all(finite(v) for v in values) or len(set(values))!=1:return {**base,'status':'missing_or_conflicting_platform_points'}
    return {**base,'status':'graded_platform_total','actual':values[0],
            'absolute_error':abs(values[0]-record['prediction']['points']),
            'result_observed_at':snapshot.synced_at.isoformat()}
