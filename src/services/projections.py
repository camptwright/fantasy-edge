"""Baseline player-prop projections: each player's own rolling mean/stddev
for a stat_type from realized results (player_game_stats), never a
fabricated league-average constant.

Depends on player_game_stats actually being populated - today that only
happens via the offline nflverse batch ingest (src/ingest/players.py's
ingest_player_stats), deliberately kept out of the serving/worker image
(pyproject.toml's `offline` extras group - the Dockerfile installs the base
package only) and run as a manual/scripted job, not on the Celery beat
schedule. A player's projection is therefore only as fresh as the last time
that job ran for the current season - the same operational model
docs/nfl-modeling.md already documented for the prior (now-removed)
predictor, `src/services/nfl_predictors.py`.

MIN_GAMES_FOR_PROJECTION mirrors that prior predictor's own threshold (see
docs/nfl-modeling.md: "A profile needs four completed games by default").
"""

from __future__ import annotations

import statistics
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import PlayerGameStat
from src.utils.odds_math import normal_cdf

MIN_GAMES_FOR_PROJECTION = 4


async def project_stats(
    db: AsyncSession, keys: set[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], tuple[float, float]]:
    """Bulk lookup: (player_id, stat_type) -> (mean, stddev) of realized
    values, for every key with enough history to qualify. One query for
    every requested player (all their stat types, not just the requested
    ones - simpler than a per-key IN-tuple query, still a single
    round-trip), matching the batched-lookup style _team_lookup/
    _rating_lookup already use in src/api/routers/sportsbook.py.
    """
    if not keys:
        return {}
    player_ids = {player_id for player_id, _ in keys}
    rows = (
        await db.execute(
            select(PlayerGameStat.player_id, PlayerGameStat.stat_type, PlayerGameStat.value).where(
                PlayerGameStat.player_id.in_(player_ids)
            )
        )
    ).all()

    grouped: dict[tuple[uuid.UUID, str], list[float]] = {}
    for player_id, stat_type, value in rows:
        grouped.setdefault((player_id, stat_type), []).append(value)

    result: dict[tuple[uuid.UUID, str], tuple[float, float]] = {}
    for key in keys:
        values = grouped.get(key)
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
