"""Trains the ELO + ensemble stack for one sport from seeded historical
games (see `scripts/seed_historical.py`) and saves a versioned model.

No-lookahead is enforced structurally, not by convention: games are walked
in chronological order, and for each game the ELO *pre-game* prediction
(`elo.predict`) is captured as a feature BEFORE `elo.update` advances the
ratings with that game's actual result. If update ran first, a game's
features would include information from its own outcome - the classic
backtest-invalidating bug this script is structured specifically to avoid.

Usage:
    python -m scripts.train_models --sport nfl --seasons 2023 2024
"""

from __future__ import annotations

import argparse
import asyncio

import pandas as pd
from sqlalchemy import select

from config.settings import get_sport_config
from src.algorithms import elo
from src.algorithms.ensemble import GameOutcomeEnsemble
from src.data.cache.db_client import get_worker_db
from src.models.orm import Game
from src.utils.logging import get_logger

log = get_logger(__name__)


async def _load_completed_games(sport: str, seasons: list[int]) -> list[Game]:
    async with get_worker_db() as db:
        result = await db.execute(
            select(Game)
            .where(
                Game.sport == sport,
                Game.status == "final",
                Game.season.in_(seasons),
                Game.home_score.is_not(None),
                Game.away_score.is_not(None),
            )
            .order_by(Game.created_at.asc())
        )
        return list(result.scalars().all())


def _build_features(sport: str, games: list[Game]) -> tuple[pd.DataFrame, pd.Series, elo.EloState]:
    cfg = get_sport_config(sport)
    elo_cfg = elo.EloConfig(**cfg["elo"])
    state = elo.EloState(config=elo_cfg)

    rows: list[dict] = []
    labels: list[int] = []

    for game in games:
        if game.home_team_id is None or game.away_team_id is None:
            continue

        pre_game = elo.predict(
            state, home_team_id=str(game.home_team_id), away_team_id=str(game.away_team_id)
        )
        rows.append(
            {
                "home_elo": state.get(str(game.home_team_id)),
                "away_elo": state.get(str(game.away_team_id)),
                "elo_home_win_probability": pre_game["home_win_probability"],
            }
        )
        labels.append(1 if game.home_score > game.away_score else 0)

        # Advance ratings with the ACTUAL result only after the feature row
        # for this game has already been captured.
        elo.update(
            state,
            home_team_id=str(game.home_team_id),
            away_team_id=str(game.away_team_id),
            home_score=game.home_score,
            away_score=game.away_score,
        )

    return pd.DataFrame(rows), pd.Series(labels), state


async def run(sport: str, seasons: list[int]) -> None:
    games = await _load_completed_games(sport, seasons)
    log.info("train_models.loaded_games", sport=sport, count=len(games))
    if len(games) < 40:
        raise SystemExit(
            f"only {len(games)} completed games for sport={sport} seasons={seasons} - "
            "need at least ~40 for a meaningful TimeSeriesSplit. Seed more seasons first."
        )

    X, y, _final_elo_state = _build_features(sport, games)

    ensemble = GameOutcomeEnsemble(sport)
    metrics = ensemble.fit(X, y)
    log.info(
        "train_models.fit_complete",
        sport=sport,
        oof_accuracy=metrics.oof_accuracy,
        oof_brier=metrics.oof_brier,
    )

    path = ensemble.save()
    print(f"Saved {sport} ensemble to {path}")
    print(
        f"OOF accuracy={metrics.oof_accuracy:.3f} brier={metrics.oof_brier:.3f} "
        f"n={metrics.n_samples} folds={metrics.n_folds}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True)
    parser.add_argument("--seasons", nargs="+", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.sport, args.seasons))


if __name__ == "__main__":
    main()
