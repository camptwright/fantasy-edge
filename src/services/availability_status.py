"""Shared provider designation vocabulary; a blank report is not game clearance."""

ALIASES = {
    'Q': 'QUESTIONABLE', 'D': 'DOUBTFUL', 'O': 'OUT',
    'INJURY_RESERVE': 'IR', 'INJURED_RESERVE': 'IR', 'INJUREDRESERVE': 'IR',
    'PHYSICALLY_UNABLE_TO_PERFORM': 'PUP', 'PUP_R': 'PUP', 'PUP_P': 'PUP',
    'SUS': 'SUSPENDED', 'SUSPENSION': 'SUSPENDED', 'COVID_19': 'COV',
    'NON_FOOTBALL_INJURY': 'NFI', 'NON_FOOTBALL_ILLNESS': 'NFI',
    'HEALTHY': 'ACTIVE', 'NORMAL': 'ACTIVE',
}
ABSENT = frozenset({'OUT', 'IR', 'PUP', 'SUSPENDED', 'NFI', 'NA', 'COV', 'DNR', 'INACTIVE'})


def normalize_status(value):
    key = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    return ALIASES.get(key, key) or None


def confirmed_absent(value):
    return normalize_status(value) in ABSENT


def normalize_team(value):
    key = str(value or '').strip().upper()
    return {'LA': 'LAR', 'JAC': 'JAX', 'WSH': 'WAS', 'OAK': 'LV', 'SD': 'LAC'}.get(key, key)
