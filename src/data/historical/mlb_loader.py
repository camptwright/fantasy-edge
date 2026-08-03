"""Historical MLB (and best-effort college baseball) results via `pybaseball`.

Deferred import: optional dependency, offline-script-only, same rationale as
nfl_loader. pybaseball also does its own on-disk caching of Statcast/schedule
pulls, which is exactly the behaviour we want for a one-off backfill script.
"""

from __future__ import annotations

from typing import Any


def load_games(season: int) -> list[dict[str, Any]]:
    import pybaseball  # deferred: optional dependency

    pybaseball.cache.enable()
    # schedule_and_record is per-team; pybaseball has no single "whole MLB
    # season" call, so pull the standings' team list first and walk it.
    teams = pybaseball.standings(season)
    team_abbrevs: set[str] = set()
    for division in teams:
        for name in division["Tm"]:
            team_abbrevs.add(name)

    rows: list[dict[str, Any]] = []
    seen_games: set[tuple[str, str, str]] = set()

    for abbrev in team_abbrevs:
        try:
            df = pybaseball.schedule_and_record(season, abbrev)
        except Exception:
            continue
        for record in df.to_dict(orient="records"):
            if record.get("W/L") is None or record.get("R") is None or record.get("RA") is None:
                continue  # unplayed game
            home_away = record.get("Home_Away")
            is_home = home_away != "@"
            opponent = record.get("Opp")
            date_str = record.get("Date")
            dedupe_key = (date_str, abbrev, opponent) if is_home else (date_str, opponent, abbrev)
            if dedupe_key in seen_games:
                continue
            seen_games.add(dedupe_key)

            runs_scored = int(record["R"])
            runs_allowed = int(record["RA"])
            rows.append(
                {
                    "sport": "mlb",
                    "season": season,
                    "game_date": date_str,
                    "home_team_name": abbrev if is_home else opponent,
                    "away_team_name": opponent if is_home else abbrev,
                    "home_score": runs_scored if is_home else runs_allowed,
                    "away_score": runs_allowed if is_home else runs_scored,
                }
            )
    return rows
