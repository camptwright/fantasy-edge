"""Verified ESPN Fantasy Football id maps.

Pulled 2026-09-09 from the raw source of the widely-used, actively
maintained `cwendt94/espn-api` community package
(espn_api/football/constant.py) rather than reconstructed from memory -
these numeric ids are undocumented by ESPN itself and getting one wrong
would silently mis-score a real player, which is worse than not
supporting that stat at all.

ESPN's PLAYER_STATS_MAP (per-player raw stat lines) and
SETTINGS_SCORING_FORMAT_MAP (a league's own scoring-weight config) share
the same numeric id space (e.g. id 3 is "passing yards" in both), so one
table below serves both jobs: translating a league's scoringItems into
Sleeper-vocabulary scoring_settings, and translating a player's raw
per-week stat line into a matching Sleeper-vocabulary "stats" dict for
src/api/main.py's existing view() to score - the exact same vocabulary
src/ingest/sleeper.py and src/services/custom_projection.py already use,
so neither needs to know or care which platform a league came from.

Deliberately narrow: only offensive skill-position stats (passing/
rushing/receiving) are translated. K and DEST scoring is NOT
reconstructed from ESPN's raw stat buckets - ESPN's own field-goal-made
buckets (under 40 / 40-49 / 50-59 / 60+) and points-allowed buckets
(0 / 1-6 / 7-13 / 14-17 / 18-21 / 22-27 / 28-34 / 35-45 / 46+) don't line
up cleanly with Sleeper's own bucket boundaries (0-19/20-29/30-39/40-49/
50+, 0/1-6/7-13/14-20/21-27/28-34/35+), so a stat-by-stat reconstruction
would silently misscore a real kicker/defense. ESPN already computes the
correct total itself (appliedTotal) using the league's real settings -
src/ingest/espn_fantasy.py uses that number directly for K/D-ST instead,
via the synthetic ESPN_APPLIED_TOTAL_KEY below. This is consistent with
src/services/custom_projection.py already treating K/DEF as unmodeled
rather than guessing.
"""

from __future__ import annotations

# player.defaultPositionId -> Sleeper-vocabulary position token. This is
# NOT the same id space as LINEUP_SLOT_MAP below (a lineup SLOT id) even
# though the community package's own POSITION_MAP dict conflates the two
# under one name - confirmed live 2026-09-09 against a real roster
# (src/ingest/espn_fantasy.py's docstring has the receipts): every real
# RB in a fetched roster carried defaultPositionId 2, every WR carried 3,
# every TE carried 4, every QB carried 1, the kicker carried 5, and the
# D/ST carried 16 - a QB/RB/WR/TE numbering offset by one from
# LINEUP_SLOT_MAP's scheme, which would have silently mis-labeled every
# WR as "RB/WR" and every TE as "WR/TE" had it been reused here.
PLAYER_POSITION_MAP: dict[int, str] = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    16: "DEF",  # ESPN's own abbreviation is "D/ST" - normalized to match
    # Sleeper's vocabulary, which src/services/custom_projection.py and
    # every player_metadata consumer in src/api/main.py already expect.
}

# ESPN lineupSlotId -> roster_positions token, for expanding a league's
# settings.rosterSettings.lineupSlotCounts (slotId -> count) into a flat
# list matching Sleeper's own roster_positions shape (e.g.
# ["QB","RB","RB","WR","WR","TE","FLEX","K","DEF","BN","BN",...]) - the
# exact shape src/api/main.py's build_starting_lineup() already consumes
# unchanged. Only slots this app's FLEX_ELIGIBILITY/RESERVE_SLOTS already
# understand are included; an unrecognized slotId is skipped rather than
# guessed (src/ingest/espn_fantasy.py logs it).
LINEUP_SLOT_MAP: dict[int, str] = {
    0: "QB",
    2: "RB",
    3: "RB",  # RB/WR - closest existing FLEX-eligible token this app has
    4: "WR",
    5: "WR",  # WR/TE
    6: "TE",
    16: "DEF",
    17: "K",
    20: "BN",
    21: "IR",
    23: "FLEX",
}
SUPER_FLEX_SLOT_ID = 7  # "OP" (offensive player) - ESPN's superflex-equivalent slot

PRO_TEAM_MAP: dict[int, str] = {
    0: None, 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# statId -> Sleeper-vocabulary scoring key. Multiple ESPN ids mapping to
# the same key (41/53 for receptions, 42/61 for receiving yards) are
# ESPN's own documented near-duplicates (cwendt94/espn-api's constant.py
# carries both with a "TODO: figure out the difference" comment) - mapped
# defensively so whichever one a given league's real config happens to
# use is still captured.
STAT_ID_TO_KEY: dict[int, str] = {
    3: "pass_yd",
    4: "pass_td",
    19: "pass_2pt",
    20: "pass_int",
    24: "rush_yd",
    25: "rush_td",
    26: "rush_2pt",
    41: "rec",
    53: "rec",
    42: "rec_yd",
    61: "rec_yd",
    43: "rec_td",
    44: "rec_2pt",
    72: "fum_lost",
}

# Injected into both a K/DEF player's translated "stats" dict (with this
# single key holding ESPN's own appliedTotal) and, once, into the
# league's translated scoring_settings (weight 1.0) - see this module's
# docstring for why K/DEF bypass STAT_ID_TO_KEY entirely.
ESPN_APPLIED_TOTAL_KEY = "_espn_applied_total"
