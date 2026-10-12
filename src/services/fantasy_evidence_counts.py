"""Descriptive evidence accounting, not independent sample sizes."""
from collections import Counter


def result_backlog(records, grades):
    """Count repair targets rather than repeated versions/league captures.

    Keep unknown old report reasons unknown. Absence does not establish DNP.
    A target may have multiple reasons across scoring contracts; those counts
    overlap and are not independent observations or mutually exclusive totals.
    """
    by_id={r['id']:r for r in records}
    pairs=set(); games=set(); captures=0; reasons={}; categories={}
    for grade in grades:
        if grade.get('status')!='missing_scoring_results' or grade['id'] not in by_id:
            continue
        record=by_id[grade['id']]
        key=(record['player_id'],record['game_id'])
        captures+=1; pairs.add(key); games.add(record['game_id'])
        reasons.setdefault(grade.get('result_blocker','unclassified_legacy_result'),set()).add(key)
        for category in grade.get('missing',[]):
            categories.setdefault(category,set()).add(key)
    return {'blocked_captures':captures,'unique_player_games':len(pairs),
        'unique_games':len(games),'additional_captures':captures-len(pairs),
        'player_games_by_blocker':{k:len(v) for k,v in sorted(reasons.items())},
        'player_games_by_missing_category':{k:len(v) for k,v in sorted(categories.items())},
        'scope':'Repair targets deduplicated across leagues and versions, not independent trials. Blocker/category counts overlap. Missing rows do not establish zero or DNP.'}


def lineup_counts(records, grades, current_version):
    """Keep older recipe outcomes separate from the currently loaded recipe."""
    experiments=[r for r in records if r.get('lineup_experiment')]
    by_id={g['id']:g for g in grades}
    statuses=Counter(); current=Counter(); unique=set(); graded=set()
    for record in experiments:
        result=by_id.get(record['id'],{})
        status=result.get('lineup_experiment',{}).get('status',result.get('status','not_evaluated'))
        statuses[status]+=1
        if record['version']==current_version:current[status]+=1
        # Frozen game set separates seasons without assuming week is globally unique.
        key=(record['league_id'],record['week'],tuple(sorted(g['id'] for g in record['lineups']['games'])))
        unique.add(key)
        if status=='graded':graded.add(key)
    return {'current_version':current_version,'counts':dict(statuses),
        'current_version_counts':dict(current),'unique_matchup_slates':len(unique),
        'unique_graded_matchup_slates':len(graded),
        'scope':'Versioned captures are not independent trials; older recipe grades do not qualify the current recipe.'}


def provider_counts(records, grades):
    by_id={g['id']:g for g in grades}
    def key(r):return (r['league_id'],r['player_id'],r['game_id'])
    unique={key(r) for r in records}
    graded={key(r) for r in records if by_id.get(r['id'],{}).get('status')=='graded_platform_total'}
    return {'captures':len(records),'unique_league_player_games':len(unique),
        'additional_versioned_captures':len(records)-len(unique),
        'unique_graded_league_player_games':len(graded),
        'captures_by_recipe':dict(Counter(r.get('recipe','unknown') for r in records)),
        'scope':'Descriptive counts only; players in the same game and across leagues are correlated. No pooled performance or promotion.'}
