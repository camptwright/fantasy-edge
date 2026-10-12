"""League-total specialist research. Corrected outcomes are never prospective proof.

Fixed candidate: four prior position-cohort pseudo-games plus up to eight own
games. Evaluate against own-history mean on the identical eligible sample.
No zero imputation, pooled league scoring, or automatic serving promotion.
"""
from collections import defaultdict
from statistics import fmean
from src.services.roster_stat_model import finite


def ros_research(players, snapshots, league, catalog, week, now):
    """Constant-role, conditional full-score horizon; no serving promotion.

    Every weekly score is observed under this league's exact scoring contract.
    This is not a participation or injury-recovery model.
    """
    from src.services.fantasy_score_history import scoring_hash
    contract=scoring_hash(league.scoring_settings,
        league.raw.get('scoringSettings') if league.platform=='espn' else None)
    history=defaultdict(list); cohorts=defaultdict(list)
    for snapshot in sorted(snapshots,key=lambda s:s.week):
        payload=snapshot.payload
        if (snapshot.kind!='scored_history' or snapshot.league_id!=league.league_id
            or snapshot.week>=week or snapshot.synced_at>now or not isinstance(payload,dict)
            or payload.get('schema_version')!=1 or payload.get('season')!=str(league.season)
            or payload.get('week')!=snapshot.week or payload.get('scoring_hash')!=contract):continue
        stored_contract=payload.get('scoring_contract')
        if not isinstance(stored_contract,dict):continue
        stored_hash=(scoring_hash(stored_contract.get('scoring'),stored_contract['official_rules'])
                     if 'official_rules' in stored_contract else scoring_hash(stored_contract))
        if stored_hash!=contract:continue
        for pid,points in payload.get('points',{}).items():
            if not finite(points):continue
            history[pid].append(points)
            position=catalog.get(pid,{}).get('position')
            if position:cohorts[position].append(points)
    output={}
    for p in players:
        metadata=catalog.get(p['player_id'],{})
        rookie=(type(metadata.get('years_exp')) is int and metadata['years_exp']==0
                and metadata.get('experience_season')==str(league.season))
        if p.get('position') not in ('K','DEF','DST') and not rookie:continue
        estimate=forecast(history[p['player_id']],cohorts[p.get('position')])
        games=p.get('next_games',[])
        complete=(p.get('ros',{}).get('status')=='complete_schedule_candidate'
                  and bool(games))
        dated=complete and all(g.get('kickoff') for g in games)
        output[p['player_id']]={**estimate,'cohort':'rookie' if rookie else p['position'],
            'scoring_hash':contract,'remaining_games':len(games),
            'horizon_status':('complete_dated_schedule' if dated else
                'complete_schedule_unknown_kickoffs' if complete else 'incomplete_schedule'),
            'conditional_ros_points':round(estimate['points']*len(games),2)
                if complete and estimate['points'] is not None else None,
            'scope':'Constant-role full-score research conditional on playing every listed game; no calibrated ROS probability or injury recovery. Not promoted.'}
    return output

RECIPE = 'specialist_full_score_shrinkage_v1'


def forecast(prior, cohort):
    """Explicitly research-only per-game output; caller must supply prior-only totals."""
    own = [float(v) for v in prior if finite(v)][-8:]
    peers = [float(v) for v in cohort if finite(v)]
    base = {'recipe':RECIPE, 'serving_promoted':False, 'ros_points':None,
            'scope':'observed_participant_per_week_not_full_ros', 'games':len(own)}
    if len(own)<2 or not peers:
        return {**base, 'status':'insufficient_history', 'points':None, 'baseline':None}
    return {**base, 'status':'research_candidate', 'baseline':fmean(own),
            'points':(sum(own)+4*fmean(peers))/(len(own)+4)}


def holdout(rows, *, holdout_season):
    keys = [(r['season'], r['week'], r['player_id']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate player week')
    contracts = {(r['league_id'], r['scoring_hash']) for r in rows}
    if len(contracts) > 1:
        raise ValueError('mixed league or scoring contract')
    histories = defaultdict(list)
    cohorts = defaultdict(list)
    evaluated = defaultdict(list)
    excluded = defaultdict(int)
    weeks = defaultdict(list)
    for row in rows:
        if row['season'] <= holdout_season:
            weeks[(row['season'], row['week'])].append(row)
    for (season, week), slate in sorted(weeks.items()):
        # Forecast the ENTIRE week before adding any outcome: no peer leakage.
        for row in slate:
            position = row['position']
            group = ('kicker' if position == 'K' else 'dst' if position in ('DEF', 'DST')
                     else 'rookie' if row.get('rookie_verified') is True else None)
            if group is None or season != holdout_season:
                continue
            prior = histories[row['player_id']][-8:]
            pool = cohorts[position]
            if not finite(row.get('points')) or len(prior) < 2 or not pool:
                excluded[group] += 1
                continue
            estimate = forecast(prior,pool)
            baseline = estimate['baseline']
            prediction = estimate['points']
            evaluated[group].append({'player_id':row['player_id'], 'week':week,
                'baseline_error':abs(row['points'] - baseline),
                'candidate_error':abs(row['points'] - prediction)})
        for row in slate:
            if finite(row.get('points')):
                histories[row['player_id']].append(float(row['points']))
                cohorts[row['position']].append(float(row['points']))
    result = {}
    for group in ('rookie', 'kicker', 'dst'):
        values = evaluated[group]
        b = fmean(r['baseline_error'] for r in values) if values else None
        c = fmean(r['candidate_error'] for r in values) if values else None
        result[group] = {'n':len(values), 'players':len({r['player_id'] for r in values}),
            'excluded':excluded[group], 'baseline_mae':b, 'candidate_mae':c,
            'decision':'retain_baseline' if not values or c >= b else 'prospective_validation_required'}
    return {'recipe':RECIPE, 'holdout_season':holdout_season, 'cohorts':result,
        'serving_promoted':False, 'scope':'retrospective_full_score_observed_player_weeks_not_ros',
        'limitations':['Observed participants only; absent rows are not zero.',
            'Current corrected archives do not prove point-in-time availability.',
            'Rookie cohort requires explicit season-specific verified evidence.',
            'Per-week improvement does not validate ROS participation or totals.']}
