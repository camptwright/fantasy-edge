"""Presentation only, outside the fantasy recipe glob; no forecast or promotion."""
from math import isfinite


def bind_defense_identities(data, teams, espn_defenses=()):
    """Corroborate defense IDs with provider evidence and one canonical NFL team.

    No name matching or numeric ESPN ID guessing. Keep forecast identity unchanged;
    this separate presentation binding cannot qualify ROS or a model promotion.
    """
    aliases = {'LA': 'LAR', 'JAC': 'JAX', 'WSH': 'WAS'}
    def abbr(value):
        value = str(value or '').strip().upper()
        return aliases.get(value, value)
    index = {}
    for team in teams:
        if team.get('sport') == 'nfl' and team.get('id') and team.get('abbr'):
            index.setdefault(abbr(team['abbr']), []).append(team)
    players = []
    espn_ids = {}
    for evidence in espn_defenses:
        if evidence.get('player_id') is not None:
            espn_ids.setdefault(str(evidence['player_id']), set()).add(str(evidence.get('team_id')))
    for player in data.get('players', []):
        if player.get('position') not in ('DEF', 'DST'):
            players.append(player)
            continue
        matches = index.get(abbr(player.get('team')), [])
        bound = (player.get('weekly_evidence', {}).get('source') == 'sleeper'
                 and abbr(player.get('player_id')) == abbr(player.get('team'))
                 and len(matches) == 1)
        if player.get('weekly_evidence', {}).get('source') == 'espn' and len(matches) == 1:
            provider_ids = espn_ids.get(str(player.get('player_id')), set())
            bound = (bool(matches[0].get('espn_id'))
                     and provider_ids == {str(matches[0]['espn_id'])})
        players.append({**player, '_workspace_team_identity': {
            'status': 'exact_team' if bound else 'unresolved_team',
            'canonical_team_id': str(matches[0]['id']) if bound else None}})
    return {**data, 'players': players}


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def uncertainty_evidence(player):
    evidence = player.get('distribution_evidence') or {}
    samples = player.get('score_samples') or []
    # Count only finite observed samples; an assumed positional prior is not history.
    valid = [x for x in samples if isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x)]
    source = player.get('distribution_source') or 'unknown'
    assumed = source == 'assumed_specialist_default' or evidence.get('status') == 'assumed_position_prior'
    return {
        'source': source,
        'status': evidence.get('status') or 'unknown',
        'observed_samples': 0 if assumed else len(valid),
        'reconciliation_samples': count(evidence.get('reconciliation_samples')),
        'reconciliation_mismatches': count(evidence.get('reconciliation_mismatches')),
        'assumed_prior': assumed,
        'scope': 'historical_variability_not_ros_or_prospective_validation',
    }


def availability_evidence(player):
    if player.get('position') in ('DEF', 'DST'):
        return 'team_unit_not_individual_injury_status'
    designation = str(player.get('injury_status') or '').strip().upper()
    if not designation:
        return 'unconfirmed_missing_designation'
    if designation in ('ACTIVE', 'HEALTHY', 'NORMAL'):
        return 'no_restriction_reported_not_game_clearance'
    return 'reported_restriction_requires_review'
