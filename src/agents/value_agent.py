"""CONSTRAINT #3: class name is `ValueAgent`.

The core pipeline: load ratings -> ELO -> Poisson -> ensemble -> blend ->
EV per book line -> dedupe best per market/side -> persist `BetSignal` ->
publish + trigger alerts.

Two design choices worth calling out because they're not obvious from the
Phase 3 algorithm modules alone:

1. **ELO ratings are persisted, not replayed from scratch every run.**
   `power_rankings` holds the latest rating per team; `_load_elo_state`
   seeds from there and only walks forward through games that finished
   *since* the last persisted rating, updating and re-persisting as it
   goes. Replaying an entire season's history on every ValueAgent
   invocation (which can run every few minutes off `OddsMonitor`'s line-
   movement trigger) would be wasteful and gets slower every day of the
   season for no benefit - the walk-forward math is identical either way
   since ELO updates are inherently incremental.
2. **The ensemble model is optional at inference time.** `scripts/train_
   models.py` has to be run at least once per sport before a trained
   pickle exists; a fresh sport has none. Rather than crash, the blend
   weight ELO+Poisson would have shared with the ensemble is redistributed
   proportionally between them - the same "don't require an upstream
   step that may not have happened yet" principle as constraint #12
   (parlay generation must not require `bet_signals` to be non-empty).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_sport_config
from src.algorithms import elo, poisson
from src.algorithms.ensemble import GameOutcomeEnsemble
from src.algorithms.ev_calculator import EVResult, evaluate
from src.algorithms.kelly import fractional_kelly_stake
from src.data.cache.redis_client import CHANNEL_LINE_MOVEMENT, get_worker_redis
from src.models.orm import BetSignal, Game, ModelOutput, OddsSnapshot, PowerRanking
from src.models.sports import MarketAssessment
from src.services.model_health import calibration_state
from src.utils.odds_math import probability_to_american
from src.utils.logging import get_logger

log = get_logger(__name__)

LEAGUE_AVG_SCORE_BY_SPORT = {
    # Rough per-team, per-game scoring averages used as the Dixon-Coles
    # league baseline. Approximate on purpose - `expected_goals_from_
    # ratings` only needs these to set the right order of magnitude; the
    # attack/defense multipliers (relative to a team's own recent scoring)
    # do the real work of separating strong and weak offenses.
    "nfl": 22.5, "ncaaf": 27.0, "nba": 113.0, "wnba": 82.0, "ncaam": 72.0,
    "nhl": 3.0, "mlb": 4.5, "ncaabaseball": 6.0,
}


class ValueAgent:
    async def _load_elo_state(self, db: AsyncSession, sport: str) -> elo.EloState:
        cfg = get_sport_config(sport)
        state = elo.EloState(config=elo.EloConfig(**cfg["elo"]))

        latest = await db.execute(
            select(PowerRanking.team_id, PowerRanking.elo_rating, PowerRanking.as_of)
            .distinct(PowerRanking.team_id)
            .where(PowerRanking.sport == sport)
            .order_by(PowerRanking.team_id, PowerRanking.as_of.desc())
        )
        latest_rows = latest.all()
        for team_id, elo_rating, _as_of in latest_rows:
            state.ratings[str(team_id)] = elo_rating
        cutoff = max((row[2] for row in latest_rows), default=None)

        conditions = [
            Game.sport == sport,
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        ]
        if cutoff is not None:
            conditions.append(Game.updated_at > cutoff)
        result = await db.execute(select(Game).where(*conditions).order_by(Game.updated_at.asc()))
        newly_final = result.scalars().all()

        now = datetime.now(timezone.utc)
        for game in newly_final:
            if game.home_team_id is None or game.away_team_id is None:
                continue
            elo.update(
                state,
                home_team_id=str(game.home_team_id),
                away_team_id=str(game.away_team_id),
                home_score=game.home_score,
                away_score=game.away_score,
            )
            db.add(
                PowerRanking(
                    sport=sport,
                    team_id=game.home_team_id,
                    elo_rating=state.get(str(game.home_team_id)),
                    season=game.season,
                    as_of=now,
                )
            )
            db.add(
                PowerRanking(
                    sport=sport,
                    team_id=game.away_team_id,
                    elo_rating=state.get(str(game.away_team_id)),
                    season=game.season,
                    as_of=now,
                )
            )
        if newly_final:
            await db.commit()
            log.info("value_agent.elo_advanced", sport=sport, games=len(newly_final))

        return state

    async def _team_scoring_rate(
        self, db: AsyncSession, sport: str, team_id: str, *, side: str, n_games: int = 10
    ) -> float | None:
        """Average points/goals/runs the team has SCORED (side="for") or
        ALLOWED (side="against") over its last `n_games` finals. None if the
        team has no completed games yet (Poisson leg falls back to blend
        weight redistribution the same as a missing ensemble)."""
        # A team appears as both home and away across its games, and which
        # column is "for" vs "against" flips depending on which side it was
        # - so this needs two queries unioned in Python, not one query on a
        # single column pair.
        home_result = await db.execute(
            select(Game.home_score if side == "for" else Game.away_score)
            .where(Game.sport == sport, Game.status == "final", Game.home_team_id == team_id)
            .order_by(Game.updated_at.desc())
            .limit(n_games)
        )
        away_result = await db.execute(
            select(Game.away_score if side == "for" else Game.home_score)
            .where(Game.sport == sport, Game.status == "final", Game.away_team_id == team_id)
            .order_by(Game.updated_at.desc())
            .limit(n_games)
        )
        scores = [s for (s,) in home_result.all() if s is not None] + [
            s for (s,) in away_result.all() if s is not None
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    async def _poisson_probability(
        self, db: AsyncSession, sport: str, game: Game
    ) -> float | None:
        league_avg = LEAGUE_AVG_SCORE_BY_SPORT.get(sport)
        if league_avg is None:
            return None
        home_for = await self._team_scoring_rate(
            db, sport, str(game.home_team_id), side="for"
        )
        home_against = await self._team_scoring_rate(
            db, sport, str(game.home_team_id), side="against"
        )
        away_for = await self._team_scoring_rate(
            db, sport, str(game.away_team_id), side="for"
        )
        away_against = await self._team_scoring_rate(
            db, sport, str(game.away_team_id), side="against"
        )
        if None in (home_for, home_against, away_for, away_against):
            return None

        home_attack = home_for / league_avg
        home_defense = home_against / league_avg
        away_attack = away_for / league_avg
        away_defense = away_against / league_avg

        lambda_home, lambda_away = poisson.expected_goals_from_ratings(
            home_attack, home_defense, away_attack, away_defense, league_avg
        )
        max_score = max(20, int(league_avg * 3))
        matrix = poisson.score_matrix(lambda_home, lambda_away, max_score=max_score)
        outcome = poisson.match_outcome_probabilities(matrix)
        # Draws are impossible/rare in most tracked sports; folding the draw
        # probability proportionally into home/away keeps this a clean
        # two-outcome number comparable to ELO/ensemble's home_win_probability.
        if outcome.home_win + outcome.away_win == 0:
            return None
        return outcome.home_win / (outcome.home_win + outcome.away_win)

    def _ensemble_probability(self, sport: str, elo_prob: float, home_elo: float, away_elo: float) -> float | None:
        try:
            model = GameOutcomeEnsemble.load_latest(sport)
        except FileNotFoundError:
            return None
        X = pd.DataFrame(
            [{"home_elo": home_elo, "away_elo": away_elo, "elo_home_win_probability": elo_prob}]
        )
        return float(model.predict_proba(X)[0])

    async def _blended_home_win_probability(
        self, db: AsyncSession, sport: str, game: Game, state: elo.EloState
    ) -> tuple[float, dict[str, float | None]]:
        cfg = get_sport_config(sport)
        weights = dict(cfg["blend"])

        elo_pred = elo.predict(
            state, home_team_id=str(game.home_team_id), away_team_id=str(game.away_team_id)
        )
        elo_prob = elo_pred["home_win_probability"]
        home_elo = state.get(str(game.home_team_id))
        away_elo = state.get(str(game.away_team_id))

        poisson_prob = await self._poisson_probability(db, sport, game)
        ensemble_prob = self._ensemble_probability(sport, elo_prob, home_elo, away_elo)

        components = {"elo": elo_prob, "poisson": poisson_prob, "ensemble": ensemble_prob}
        available = {k: v for k, v in components.items() if v is not None}
        available_weight = sum(weights.get(k, 0.0) for k in available)
        if available_weight <= 0:
            # Should only happen if elo itself is somehow missing, which
            # can't occur since elo.predict always returns a value.
            return elo_prob, components

        blended = sum(weights.get(k, 0.0) * v for k, v in available.items()) / available_weight
        return blended, components

    async def _latest_odds_for_game(
        self, db: AsyncSession, game_id: str, market: str
    ) -> dict[tuple[str, str], OddsSnapshot]:
        """Most recent snapshot per (bookmaker, outcome) for one market."""
        result = await db.execute(
            select(OddsSnapshot)
            .where(OddsSnapshot.game_id == game_id, OddsSnapshot.market == market)
            .order_by(OddsSnapshot.captured_at.desc())
        )
        latest: dict[tuple[str, str], OddsSnapshot] = {}
        for snap in result.scalars().all():
            key = (snap.bookmaker, snap.outcome)
            if key not in latest:
                latest[key] = snap
        return latest

    async def _publish_and_alert(self, signal: BetSignal) -> None:
        # Fresh client, not the API's shared get_redis() - ValueAgent only
        # ever runs inside a Celery task's own asyncio.run() loop (via
        # run_value_agent_for_game / value_agent_tick, or the odds_monitor
        # trigger). See redis_client.py's module docstring.
        async with get_worker_redis() as redis:
            await redis.publish(
                CHANNEL_LINE_MOVEMENT,
                f'{{"type":"bet_signal","signal_id":"{signal.id}","ev_percent":{signal.ev_percent}}}',
            )
        try:
            from src.scheduler.tasks import send_alert_for_signal
        except ImportError:
            log.info("value_agent.alert_agent_not_wired_yet", signal_id=str(signal.id))
            return
        send_alert_for_signal.delay(str(signal.id))

    async def evaluate_game(self, db: AsyncSession, game: Game) -> list[BetSignal]:
        """Runs the full pipeline for one game's h2h market and persists any
        BetSignal rows whose EV clears the sport's threshold."""
        sport = game.sport
        cfg = get_sport_config(sport)
        ev_threshold = cfg.get("ev_threshold_pct", 2.0)

        if game.home_team_id is None or game.away_team_id is None:
            return []

        state = await self._load_elo_state(db, sport)
        home_win_prob, components = await self._blended_home_win_probability(
            db, sport, game, state
        )
        away_win_prob = 1.0 - home_win_prob

        db.add(
            ModelOutput(
                game_id=game.id,
                sport=sport,
                model_name="blend",
                home_win_probability=home_win_prob,
                away_win_probability=away_win_prob,
                features=components,
            )
        )

        odds_by_book = await self._latest_odds_for_game(db, str(game.id), "h2h")
        if not odds_by_book:
            await db.commit()
            return []

        # Group by outcome so we can find, per side, the single best price
        # across books - constraint: dedupe best per market/side.
        by_outcome: dict[str, list[OddsSnapshot]] = {}
        for (_book, outcome), snap in odds_by_book.items():
            by_outcome.setdefault(outcome, []).append(snap)

        home_name = game.home_team_name or ""
        calibration = calibration_state(sport)
        # A new evaluation supersedes the previous board state for this game;
        # keep immutable OddsSnapshot history, but do not leave stale cards.
        await db.execute(MarketAssessment.__table__.delete().where(MarketAssessment.event_id == game.id))
        signals: list[BetSignal] = []

        for outcome, snaps in by_outcome.items():
            other_outcome_snaps = [
                s for o, ss in by_outcome.items() if o != outcome for s in ss
            ]
            if not other_outcome_snaps:
                continue
            model_prob = home_win_prob if outcome == home_name else away_win_prob
            # Best price for the bettor = the one with the highest payout,
            # i.e. the largest American price (works for + and - together
            # since e.g. +120 > -105 > -110 numerically in the direction
            # that favours the bettor).
            best_snap = max(snaps, key=lambda s: s.price_american or -10_000)
            opposing_snap = other_outcome_snaps[0]

            result: EVResult = evaluate(
                model_prob,
                best_snap.price_american,
                opposing_snap.price_american,
                ev_threshold_pct=ev_threshold,
            )
            status = "qualified" if calibration.calibrated else "uncalibrated"
            db.add(
                MarketAssessment(
                    event_id=game.id,
                    sport=sport,
                    league=sport,
                    market="h2h",
                    selection=outcome,
                    status=status,
                    status_reason=None if calibration.calibrated else "The model has no passing calibration record for this market.",
                    probability=model_prob if calibration.calibrated else None,
                    fair_price_american=probability_to_american(model_prob) if calibration.calibrated else None,
                    edge_percent=result.edge_percent if calibration.calibrated else None,
                    estimated_value_percent=result.ev_percent if calibration.calibrated else None,
                    model_version=calibration.model_version if calibration.calibrated else None,
                    source_snapshot_ids=[str(best_snap.id), str(opposing_snap.id)],
                )
            )
            if result.tier == "none":
                continue

            stake = fractional_kelly_stake(model_prob, best_snap.price_american, bankroll=1.0)
            signal = BetSignal(
                game_id=game.id,
                sport=sport,
                market="h2h",
                selection=outcome,
                bookmaker=best_snap.bookmaker,
                price_american=best_snap.price_american,
                model_probability=model_prob,
                fair_probability=result.market_fair_probability,
                implied_probability=result.market_implied_probability,
                ev_percent=result.ev_percent,
                kelly_fraction=stake,
                stake_units=stake,
                confidence=result.confidence,
                tier=result.tier,
            )
            db.add(signal)
            signals.append(signal)

        await db.commit()
        for signal in signals:
            await self._publish_and_alert(signal)

        log.info(
            "value_agent.evaluated",
            game_id=str(game.id),
            sport=sport,
            signals=len(signals),
        )
        return signals

    async def evaluate_upcoming(self, db: AsyncSession, sport: str, *, limit: int = 50) -> int:
        result = await db.execute(
            select(Game)
            .where(Game.sport == sport, Game.status == "scheduled")
            .order_by(Game.game_time.asc().nulls_last())
            .limit(limit)
        )
        games = result.scalars().all()
        total = 0
        for game in games:
            signals = await self.evaluate_game(db, game)
            total += len(signals)
        return total
