"""Strict extraction of ESPN actuals; callers must bind league scoring rules.

The historical player endpoint can omit a top-level scoringPeriodId. Individual
stat records must still bind both season and period; projections never qualify.
This parser alone does not establish finality or authorize forecast grading.
"""
from collections import defaultdict
import json
from src.services.roster_stat_model import finite


def espn_actuals(payload, *, season, week, player_ids):
    requested = set(map(str, player_ids))
    values = defaultdict(list)
    for item in payload.get('players', []):
        player = item.get('player', {})
        pid = str(player.get('id'))
        if pid not in requested:
            continue
        for stat in player.get('stats', []):
            if (stat.get('statSourceId') == 0 and stat.get('seasonId') == season
                    and stat.get('scoringPeriodId') == week):
                values[pid].append(stat.get('appliedTotal'))
    points, blockers = {}, {}
    for pid in sorted(requested):
        rows = values[pid]
        if not rows:
            blockers[pid] = 'missing_exact_period_actual'
        elif not all(finite(v) for v in rows):
            blockers[pid] = 'invalid_actual'
        elif len(set(rows)) != 1:
            blockers[pid] = 'conflicting_actuals'
        else:
            points[pid] = float(rows[0])
    return {'points': points, 'blockers': blockers}


async def collect_espn_pool(db, client, *, league_id, raw_league_id, season, week,
                            scoring, rules, roster_points, game_ids, now):
    """Called only after full-slate finality and exact-period rules checks."""
    from src.ingest.espn_fantasy import _snapshot
    from src.services.fantasy_score_history import scoring_hash
    response = await client.get(f'/seasons/{season}/segments/0/leagues/{raw_league_id}',
        params={'view':'kona_player_info','scoringPeriodId':week},
        headers={'x-fantasy-filter':json.dumps({'players':{'limit':500,
            'sortPercOwned':{'sortPriority':1,'sortAsc':False}}})})
    response.raise_for_status()
    payload=response.json()
    ids=[p.get('player',{}).get('id') for p in payload.get('players',[]) if p.get('player',{}).get('id') is not None]
    parsed=espn_actuals(payload,season=season,week=week,player_ids=ids)
    overlap=set(parsed['points']) & set(roster_points)
    conflicts=sorted(pid for pid in overlap if abs(parsed['points'][pid]-roster_points[pid])>1e-6)
    # One matching player cannot corroborate a league-wide scoring contract.
    valid=len(overlap)>=10 and not conflicts
    result={'schema_version':1,'season':str(season),'week':week,
        'scoring_hash':scoring_hash(scoring,rules),'scoring_contract':{'scoring':scoring,'official_rules':rules},
        'game_ids':sorted(game_ids),'observed_at':now.isoformat(),
        'source':'espn_league_historical_player_pool','status':'reconciled' if valid else 'unreconciled',
        'overlap_players':len(overlap),'conflicting_player_ids':conflicts,
        'points':parsed['points'] if valid else {},'blockers':parsed['blockers'],
        'scope':'bounded_500_player_pool_not_complete_league_or_roster_membership',
        'serving_promoted':False}
    await _snapshot(db,league_id,week,'historical_player_scores',result)
    return result
