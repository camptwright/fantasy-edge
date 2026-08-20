"""NFL matchup and player-stat predictors built from nflverse data.

This module deliberately contains no network or database side effects. Batch
jobs load nflverse data through :mod:`src.data.historical.nfl_loader`, build
profiles here, and only publish predictions when the explicit sample and
feature gates pass. A missing stat is never replaced with a league-average
number: returning ``qualified=False`` is safer than manufacturing confidence.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable


def _number(row: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = row.get(name)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _team(row: dict[str, Any]) -> str | None:
    value = row.get("team") or row.get("team_abbr") or row.get("recent_team")
    return str(value) if value else None


@dataclass(frozen=True)
class NFLTeamProfile:
    team: str
    games: int
    points_for_per_game: float
    points_against_per_game: float
    pass_epa_per_game: float | None
    rush_epa_per_game: float | None
    success_rate: float | None


@dataclass(frozen=True)
class NFLMatchupPrediction:
    home_team: str
    away_team: str
    expected_home_points: float | None
    expected_away_points: float | None
    home_win_probability: float | None
    confidence: str
    qualified: bool
    reason: str | None = None


def build_team_profiles(
    team_stats: Iterable[dict[str, Any]], *, min_games: int = 4
) -> dict[str, NFLTeamProfile]:
    """Aggregate nflverse team rows into the latest available team profiles.

    nflverse has changed a few column names across releases; the aliases are
    intentionally centralized here. Rows without scoring values are ignored,
    and a profile is emitted only after ``min_games`` observations.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in team_stats:
        team = _team(row)
        if team:
            grouped.setdefault(team, []).append(row)

    profiles: dict[str, NFLTeamProfile] = {}
    for team, rows in grouped.items():
        scored = [
            _number(r, ("points_for", "points", "score", "total_points"))
            for r in rows
        ]
        allowed = [
            _number(r, ("points_against", "opp_points", "opponent_score"))
            for r in rows
        ]
        scored_values = [v for v in scored if v is not None]
        allowed_values = [v for v in allowed if v is not None]
        if len(scored_values) < min_games or len(allowed_values) < min_games:
            continue
        pass_epa = [
            _number(r, ("pass_epa", "passing_epa", "offense_pass_epa"))
            for r in rows
        ]
        rush_epa = [
            _number(r, ("rush_epa", "rushing_epa", "offense_rush_epa"))
            for r in rows
        ]
        success = [_number(r, ("success_rate", "offense_success_rate")) for r in rows]

        def avg(values: list[float | None]) -> float | None:
            clean = [v for v in values if v is not None]
            return statistics.fmean(clean) if clean else None

        profiles[team] = NFLTeamProfile(
            team=team,
            games=min(len(scored_values), len(allowed_values)),
            points_for_per_game=statistics.fmean(scored_values),
            points_against_per_game=statistics.fmean(allowed_values),
            pass_epa_per_game=avg(pass_epa),
            rush_epa_per_game=avg(rush_epa),
            success_rate=avg(success),
        )
    return profiles


def predict_matchup(
    home: NFLTeamProfile,
    away: NFLTeamProfile,
    *,
    min_games: int = 4,
) -> NFLMatchupPrediction:
    """Estimate expected points and home win probability.

    The predictor is intentionally a transparent baseline for the first NFL
    release: offense/defense scoring rates plus a small home adjustment and
    optional EPA adjustment. It is not eligible for public board output until
    the caller records an out-of-fold calibration result.
    """
    if home.games < min_games or away.games < min_games:
        return NFLMatchupPrediction(
            home.team, away.team, None, None, None, "low", False,
            "both teams need the minimum completed-game sample",
        )
    home_points = ((home.points_for_per_game + away.points_against_per_game) / 2) + 1.5
    away_points = (away.points_for_per_game + home.points_against_per_game) / 2
    # EPA is used only when both sides expose it; this prevents partial feeds
    # from silently favoring teams with a more complete row schema.
    if home.pass_epa_per_game is not None and away.pass_epa_per_game is not None:
        home_points += max(-2.0, min(2.0, (home.pass_epa_per_game - away.pass_epa_per_game) / 4))
    if home.rush_epa_per_game is not None and away.rush_epa_per_game is not None:
        away_points += max(-2.0, min(2.0, (away.rush_epa_per_game - home.rush_epa_per_game) / 4))
    probability = 1 / (1 + math.exp(-(home_points - away_points) / 6.5))
    confidence = "high" if min(home.games, away.games) >= 8 else "medium"
    return NFLMatchupPrediction(
        home.team, away.team, round(home_points, 2), round(away_points, 2),
        round(probability, 4), confidence, True,
    )


@dataclass(frozen=True)
class NFLPlayerProfile:
    player: str
    team: str | None
    games: int
    stats: dict[str, float]
    standard_deviations: dict[str, float]


@dataclass(frozen=True)
class NFLPlayerStatPrediction:
    player: str
    stat: str
    projection: float | None
    floor: float | None
    ceiling: float | None
    confidence: str
    qualified: bool
    reason: str | None = None


def build_player_profiles(
    player_stats: Iterable[dict[str, Any]], *, min_games: int = 4
) -> dict[str, NFLPlayerProfile]:
    """Build player profiles from game-level nflverse rows."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in player_stats:
        name = row.get("player_name") or row.get("full_name") or row.get("name")
        if name:
            grouped.setdefault(str(name), []).append(row)
    stat_aliases = {
        "passing_yards": ("passing_yards", "pass_yards"),
        "rushing_yards": ("rushing_yards", "rush_yards"),
        "receiving_yards": ("receiving_yards", "rec_yards"),
        "receptions": ("receptions", "rec"),
        "passing_touchdowns": ("passing_touchdowns", "passing_tds", "pass_tds"),
        "rushing_touchdowns": ("rushing_touchdowns", "rushing_tds", "rush_tds"),
        "receiving_touchdowns": ("receiving_touchdowns", "receiving_tds", "rec_tds"),
        "touchdowns": ("touchdowns", "total_tds"),
        "fantasy_points": ("fantasy_points", "fantasy_points_ppr"),
    }
    profiles: dict[str, NFLPlayerProfile] = {}
    for player, rows in grouped.items():
        stats: dict[str, float] = {}
        deviations: dict[str, float] = {}
        for stat, aliases in stat_aliases.items():
            values = [v for r in rows if (v := _number(r, aliases)) is not None]
            if len(values) >= min_games:
                stats[stat] = statistics.fmean(values)
                deviations[stat] = statistics.pstdev(values)
        if not stats:
            continue
        profiles[player] = NFLPlayerProfile(
            player=player,
            team=(
                str(rows[-1].get("recent_team") or rows[-1].get("team"))
                if (rows[-1].get("recent_team") or rows[-1].get("team"))
                else None
            ),
            games=len(rows), stats=stats, standard_deviations=deviations,
        )
    return profiles


def predict_player_stat(
    profile: NFLPlayerProfile, stat: str, *, min_games: int = 4
) -> NFLPlayerStatPrediction:
    if profile.games < min_games or stat not in profile.stats:
        return NFLPlayerStatPrediction(
            profile.player, stat, None, None, None, "low", False,
            "player/stat lacks the minimum complete-game sample",
        )
    projection = profile.stats[stat]
    deviation = profile.standard_deviations.get(stat, 0.0)
    return NFLPlayerStatPrediction(
        profile.player, stat, round(projection, 2), round(max(0, projection - deviation), 2),
        round(projection + deviation, 2), "high" if profile.games >= 8 else "medium", True,
    )
