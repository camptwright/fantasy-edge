"""Historical NFL results via `nfl_data_py`.

Used only by `scripts/seed_historical.py` and `scripts/train_models.py`, both
one-off/offline scripts - never imported by the live agents - so
`nfl_data_py` (and pandas' heavier transitive deps) stay an optional install
(`pip install .[historical]`) rather than bloating the API/worker image.
The import is therefore deferred to inside the function, not module level.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def load_games(seasons: list[int]) -> list[dict[str, Any]]:
    """Final scores for each season, one row per game.

    nfl_data_py's schedule includes future/unplayed games with null scores;
    those are dropped here since backtesting needs completed results only.
    """
    import nfl_data_py as nfl  # deferred: optional dependency

    df = nfl.import_schedules(seasons)
    df = df.dropna(subset=["home_score", "away_score"])

    rows: list[dict[str, Any]] = []
    for record in df.to_dict(orient="records"):
        game_date = record.get("gameday")
        rows.append(
            {
                "sport": "nfl",
                "season": int(record["season"]),
                "week": int(record["week"]) if record.get("week") is not None else None,
                "game_date": date.fromisoformat(str(game_date)) if game_date else None,
                "home_team_name": record.get("home_team"),
                "away_team_name": record.get("away_team"),
                "home_score": int(record["home_score"]),
                "away_score": int(record["away_score"]),
            }
        )
    return rows
