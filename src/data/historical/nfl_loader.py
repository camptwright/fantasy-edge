"""Historical NFL data via ``nflreadpy``.

Used only by `scripts/seed_historical.py` and `scripts/train_models.py`, both
one-off/offline scripts - never imported by the live agents - so
``nflreadpy`` (and its Polars dependency) stays an optional install
(`pip install .[historical]`) rather than bloating the API/worker image.
The import is therefore deferred to inside the function, not module level.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def load_games(seasons: list[int]) -> list[dict[str, Any]]:
    """Final scores for each season, one row per game.

    nflreadpy's schedule includes future/unplayed games with null scores;
    those are dropped here since backtesting needs completed results only.
    """
    nfl = _nflreadpy()

    records = _records(nfl.load_schedules(seasons))

    rows: list[dict[str, Any]] = []
    for record in records:
        if record.get("home_score") is None or record.get("away_score") is None:
            continue
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


def _nflreadpy() -> Any:
    """Import the optional provider with an actionable installation error."""
    try:
        import nflreadpy as nfl  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in batch envs
        raise RuntimeError(
            "NFL historical ingestion requires nflreadpy; install with "
            "pip install 'fantasy-edge[historical]'"
        ) from exc
    return nfl


def _records(frame: Any) -> list[dict[str, Any]]:
    """Convert nflreadpy's Polars frame without making Polars a runtime dep."""
    if hasattr(frame, "to_dicts"):
        return list(frame.to_dicts())
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict(orient="records"))
    return list(frame)


def load_team_stats(seasons: list[int]) -> list[dict[str, Any]]:
    """Load nflverse team-game/season statistics for offline predictors."""
    nfl = _nflreadpy()
    return _records(nfl.load_team_stats(seasons))


def load_player_stats(seasons: list[int]) -> list[dict[str, Any]]:
    """Load nflverse player-game statistics for offline player projections."""
    nfl = _nflreadpy()
    return _records(nfl.load_player_stats(seasons))


def load_players() -> list[dict[str, Any]]:
    """Load the nflverse player identity table for cross-provider joins."""
    nfl = _nflreadpy()
    return _records(nfl.load_players())
