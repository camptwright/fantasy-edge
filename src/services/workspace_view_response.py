"""Small tool views; detailed player evidence is retrieved separately."""
SUMMARY={'player_id','name','position','team','points','source','locked','injury_status',
 'normalized_injury_status','reserve_slot','ownership','roster_id','roster_names',
 'engine_status','engine_week_points','engine_ros_points','engine_ros_games',
 'consensus_week_points','sos_ros_stars','sos_next4_stars','play_probability',
 'week_game_status','week_kickoff','game_availability_hold','opponent','identity_status',
 'availability_status','decision_tier'}
COMMON={'schema_version','league_id','status','message','actionable','generated_at','expires_at',
        'week','model_version','recipe_version','scoring_contract_hash'}
TOOLS={
 'today':{'starters','roster_players','matchup','lineup_changes','outcomes','strength','season_accuracy','late_swap'},
 'overview':{'starters','roster_players','matchup','lineup_changes','outcomes','strength','season_accuracy','late_swap'},
 'team':{'starters','roster_players','matchup','lineup_changes','outcomes','late_swap'},
 'startsit':{'roster_players','outcomes','late_swap'},
 'waivers':{'engine_waivers','waivers','comparison_players','roster_players','strength','research'},
 'players':{'comparison_players','matchup','starters','lineup_changes','research'},
 'player':{'comparison_players','outcomes'},'trade':{'comparison_players'},
 'league':{'strength','comparison_players'},'recap':set(),
 'journal':{'roster_players','comparison_players','engine_waivers','matchup'},
}


def trim(overview,tool,selected=()):
    raw=overview.model_dump(mode='json',exclude_unset=True)
    result={k:v for k,v in raw.items() if k in COMMON|TOOLS[tool]}
    for field in ('comparison_players','roster_players'):
        if field not in result:continue
        rows=result[field]
        if tool=='player':rows=[p for p in rows if p['player_id'] in selected]
        result[field]=[{k:v for k,v in p.items() if field=='roster_players' or p['player_id'] in selected or k in SUMMARY} for p in rows]
    if 'outcomes' in result:
        if tool=='player':result['outcomes']['player_ranges']={k:v for k,v in result['outcomes'].get('player_ranges',{}).items() if k in selected}
        elif tool not in ('startsit','team'):result['outcomes'].pop('player_ranges',None)
    return result
