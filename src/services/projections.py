"""Baseline player-prop projections: each player's eligible-history mean/stddev
for a stat_type from realized results (player_game_stats), never a
fabricated league-average constant.

Reads eligible realized results at request time, including scheduled result
ingestion and historical backfills. New final results affect projections
without retraining coefficients; pending corrections remain excluded.

MIN_GAMES_FOR_PROJECTION mirrors that prior predictor's own threshold (see
docs/nfl-modeling.md: "A profile needs four completed games by default").
"""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.utils.odds_math import normal_cdf
from src.services.stat_identity import canonical_stat, canonical_results, ALIASES
from src.services.result_eligibility import no_pending_correction

MIN_GAMES_FOR_PROJECTION = 4


async def project_stats(
    db: AsyncSession, keys: set[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], tuple[float, float]]:
    """Bound memory by player batch; keep the all-history numerical recipe."""
    players = sorted({pid for pid, _ in keys}, key=str)
    result = {}
    for start in range(0, len(players), 24):
        batch = set(players[start:start+24])
        result.update(await _project_stats_batch(db, {k for k in keys if k[0] in batch}))
    return result


async def _project_stats_batch(
    db: AsyncSession, keys: set[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], tuple[float, float]]:
    """Bulk lookup: (player_id, stat_type) -> (mean, stddev) of realized
    values, for every key with enough history to qualify. One query for
    every requested player. Fetch lightweight fact columns for requested
    canonical stats and aliases, not full ORM objects for unrelated outcomes.
    """
    if not keys:
        return {}
    player_ids = {player_id for player_id, _ in keys}
    stats = {canonical_stat(stat) for _, stat in keys}
    stats |= {alias for alias, canonical in ALIASES.items() if canonical in stats}
    rows = (
        await db.execute(
            select(PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type,
                   PlayerGameStat.value).join(Game, Game.id == PlayerGameStat.game_id)
                .join(Player, Player.id == PlayerGameStat.player_id).where(
                Game.sport == Player.sport,
                PlayerGameStat.stat_type.in_(stats),
                PlayerGameStat.player_id.in_(player_ids), Game.status == 'final',
                no_pending_correction(),
                or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
                Game.game_time.isnot(None),
                or_(Game.game_time.is_(None), Game.game_time < datetime.now(timezone.utc))
            )
        )
    ).all()

    grouped: dict[tuple[uuid.UUID, str], list[float]] = {}
    for (player_id, game_id, stat_type), value in canonical_results(rows).items():
        grouped.setdefault((player_id, stat_type), []).append(value)

    result: dict[tuple[uuid.UUID, str], tuple[float, float]] = {}
    for key in keys:
        values = grouped.get((key[0], canonical_stat(key[1])))
        if values is None or len(values) < MIN_GAMES_FOR_PROJECTION:
            continue
        mean = statistics.fmean(values)
        stddev = statistics.pstdev(values, mu=mean)
        if stddev <= 0:
            # Every realized game identical so far (e.g. zero interceptions
            # in all four) - a zero-width distribution makes
            # over_probability degenerate to exactly 0 or 1, which reads as
            # false certainty rather than "not enough variation observed
            # yet". Treat as not-yet-qualified instead.
            continue
        result[key] = (mean, stddev)
    return result


def over_probability(mean: float, stddev: float, line: float) -> float:
    """P(realized value > line), modelling the stat as Normal(mean,
    stddev) - the same normal-approximation baseline as the totals/spread
    models (src/services/totals.py, src/services/elo.py), not a
    stat-specific fitted distribution."""
    return 1.0 - normal_cdf((line - mean) / stddev)
