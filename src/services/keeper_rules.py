"""Owner-confirmed keeper rules; eligibility/cost arithmetic, not player pricing."""
LEAGUE_ID = '1398509004950376448'
RULES = {
    'version': 'owner_confirmed_one_keeper_v1',
    'max_keepers': 1,
    'consecutive_years_allowed': False,
    'first_round_draftees_allowed': False,
    'cost_round_offset': -1,
    'source': 'league_owner_confirmation',
    'unresolved': ['undrafted_player_cost', 'traded_player_draft_cost_basis',
                   'unavailable_cost_pick_handling'],
}


def evaluate(league_id, players):
    if league_id != LEAGUE_ID:
        return {'status': 'unconfigured_league', 'actionable': False, 'players': []}
    results=[]
    for player in players:
        blockers=[]
        draft=player.get('draft_round')
        kept=player.get('kept_last_year')
        if type(draft) is not int or draft < 1:
            blockers.append('missing_or_invalid_draft_round')
        elif draft == 1:
            blockers.append('first_round_draftee_ineligible')
        if kept is True:
            blockers.append('consecutive_year_keeper_ineligible')
        elif kept is not False:
            blockers.append('previous_keeper_status_unknown')
        if player.get('original_drafter') is not True:
            blockers.append('original_draft_cost_basis_unconfirmed')
        if player.get('cost_pick_available') is not True:
            blockers.append('cost_pick_availability_unconfirmed')
        disqualified=any(b.endswith('_ineligible') for b in blockers)
        from src.services.keeper_valuation import value_scenario
        valuation=value_scenario(league_id, player['player_id'],
                                 draft-1 if type(draft) is int and draft>1 else None,
                                 player.get('valuation'))
        results.append({'player_id':player['player_id'], 'valuation':valuation,
            'status':'ineligible' if disqualified else 'unresolved' if blockers else 'eligible_under_supplied_evidence',
            'cost_round':draft-1 if type(draft) is int and draft>1 else None,
            'blockers':blockers})
    ids=[p['player_id'] for p in players]
    selection=[]
    if len(players)>1: selection.append('one_keeper_maximum')
    if len(ids)!=len(set(ids)): selection.append('duplicate_player')
    return {'status':'selection_invalid' if selection else 'eligibility_review',
            'rules':RULES,'actionable':False,'selection_blockers':selection,'players':results,
            'scope':'Supplied evidence only; optional next-season surplus scenario is not verified pricing. No selection submission or model promotion.'}
