"""A second, independent player-projection source for the fantasy pages,
separate from Sleeper's own model.

Underdog Fantasy's player-props API - the original plan for a second
source - now rejects every request with a deliberate version-gate
("api_code":"upgrade_required"), confirmed live 2026-09-09 with realistic
browser headers, HTTP/2, and no bot-detection signal in the response;
that is a vendor access-control decision to work around, not a bug to fix,
so it was not pursued further.

This module instead derives a projection from data this app already has:
each player's own real 2025 season per-game average, from play-by-play-
derived `player_game_stats`, scored under the SAME league scoring_settings
Sleeper's projection is scored under - directly comparable, but built from
a genuinely different source and method (realized history, not whatever
model Sleeper runs). It is deliberately simple and disclosed as such: a
recency-blind season average, not adjusted for the 2026 offseason (trades,
injuries, depth-chart changes, rookies with zero 2025 NFL snaps). A
starting player with no 2025 NFL games (rookies, practice-squad call-ups)
correctly gets no custom projection rather than a fabricated one.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player

# player_game_stats.stat_type (this app's own naming, from nfl_pbp_props.py)
# -> the Sleeper scoring_settings key it corresponds to. Only stats fantasy
# scoring actually uses are mapped; attempts/completions/targets etc. have
# no scoring weight in any real league and are left out on purpose.
_STAT_TYPE_TO_SCORING_KEY = {
    "passing_yards": "pass_yd",
    "passing_touchdowns": "pass_td",
    "passing_interceptions": "pass_int",
    "rushing_yards": "rush_yd",
    "rushing_touchdowns": "rush_td",
    "receiving_yards": "rec_yd",
    "receiving_touchdowns": "rec_td",
    "receptions": "rec",
}

_SUFFIX_RE = re.compile(r"\s+(jr\.?|sr\.?|i{2,3}|iv)$", re.IGNORECASE)


def normalize_name(name: str) -> str:
    """Lowercase, period-stripped, suffix-stripped - enough to match most
    real name-spelling differences between Sleeper and this app's own
    nflverse-derived player records without over-matching distinct
    players. Confirmed live 2026-09-09: 7 of 8 real roster names matched
    on exact full_name alone; the one miss was a suffix difference
    ("Kenneth Walker" vs "Kenneth Walker III"), which this normalization
    is specifically for."""
    return _SUFFIX_RE.sub("", name.strip().lower()).replace(".", "")


async def load_2025_averages(db: AsyncSession) -> dict[str, dict[str, float]]:
    """One batched query for every NFL player's per-stat-type average
    across all of the 2025 season - called once per request, not once per
    player, since a roster-sized N+1 here would be 20-30 queries for no
    reason. Returns {normalized_name: {stat_type: avg_value}}."""
    # BUG FOUND LIVE 2026-09-09: selecting Player.full_name alongside
    # PlayerGameStat/Game columns without an explicit Player join gave
    # SQLAlchemy no relationship to infer one from, so it silently emitted
    # `FROM player_game_stats JOIN games ..., players` - a plain
    # comma-joined cartesian product against all 24,832 NFL players, not a
    # real join at all. That blew a temp-file sort out to "No space left
    # on device" on a query that should return a few thousand grouped
    # rows. The explicit .join(Player, ...) below is required, not
    # decorative.
    rows = (
        await db.execute(
            select(Player.full_name, PlayerGameStat.stat_type, func.avg(PlayerGameStat.value))
            .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
            .join(Game, Game.id == PlayerGameStat.game_id)
            .where(Player.sport == "nfl", Game.sport == "nfl", Game.season == 2025)
            .group_by(Player.full_name, PlayerGameStat.stat_type)
        )
    ).all()
    averages: dict[str, dict[str, float]] = {}
    for full_name, stat_type, avg_value in rows:
        averages.setdefault(normalize_name(full_name), {})[stat_type] = float(avg_value)
    return averages


# Positions this model has no scoring category for at all - field goals,
# extra points, and team defense/special-teams scoring (points allowed,
# sacks, return TDs, ...) aren't in player_game_stats as per-player rows
# the way passing/rushing/receiving are. Checked by position, not by
# whether a stat row exists: confirmed live 2026-09-09 that the pbp-
# derived pipeline inserts an explicit 0 for passing_yards/rushing_yards/
# etc. for EVERY player who appeared in a game at all, kickers included -
# so "does a mapped stat key exist" can never distinguish a kicker from
# an offensive player who legitimately produced nothing.
_UNMODELED_POSITIONS = {"K", "DEF"}


def custom_projected_points(
    scoring_settings: dict, sleeper_player_name: str, averages: dict[str, dict[str, float]], position: str | None = None
) -> float | None:
    """None (not 0.0) means this model has nothing to say for this player
    - either their position isn't modeled at all (see _UNMODELED_POSITIONS)
    or genuinely no 2025 NFL history was found for their name (rookie,
    practice-squad call-up, name mismatch). Either way it should read as
    "no data" in the UI, never be mistaken for "projected to score zero.\""""
    if position in _UNMODELED_POSITIONS:
        return None
    stats = averages.get(normalize_name(sleeper_player_name))
    if stats is None:
        return None
    points = sum(
        stats.get(stat_type, 0.0) * float(scoring_settings.get(scoring_key, 0) or 0)
        for stat_type, scoring_key in _STAT_TYPE_TO_SCORING_KEY.items()
    )
    return round(points, 2)
