"""Cross-source data-health checks: source freshness and price divergence.

Two checks, matching the scraping build-out plan's Phase 2 ("large
divergence or an empty result from one source is itself the canary signal
- no separate check needed"):

1. Freshness - is each source's own scheduled run actually succeeding on
   its own cadence. Deliberately reads `ingestion_runs` (was this source's
   Celery task recently successful), never `rows_written` counts or
   line-table recency: `record_team_line`/`record_prop_line` only WRITE a
   row when the value actually changed (see src/ingest/lines.py's own
   docstring), so `rows_written == 0` is the normal steady-state outcome
   once a market has stopped moving, not an anomaly. A run-based check is
   the only one that can't false-alarm on a perfectly healthy, unchanged
   market.
2. Divergence - do the team-market sources agree with each other closely
   enough. This app's own CLAUDE.md constraint history (the ESPN/nflverse
   spread-sign mirror-image bug, constraint #24's team-identity bugs) is
   exactly the failure class this catches: a parsing/sign bug in one
   source typically produces a gap far larger than any two real
   sportsbooks would ever organically disagree by.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.models.base import utcnow
from src.models.facts import Game, TeamMarketLine
from src.models.governance import IngestionRun
from src.utils.odds_math import american_to_implied

# Seconds, mirroring celery_app.py's beat_schedule intervals.
_SOURCE_INTERVALS = {
    "espn": 900, "underdog": 900, "sleeper": 900,
    "theodds": 1800, "pinnacle": 1800, "bovada": 1800, "prizepicks": 1800,
}
_MULTI_SPORT_SOURCES = ("espn", "theodds", "pinnacle", "bovada")
_SINGLE_RUN_SOURCES = ("underdog", "sleeper", "prizepicks")
# How many missed intervals before flagging - slack for one transient
# failure or a single missed beat tick without false-alarming on jitter.
_STALE_MULTIPLIER = 3

# Divergence large enough to be a parsing bug (a sign error roughly
# doubles the observed gap) rather than genuine market disagreement between
# books.
_SPREAD_DIVERGENCE_POINTS = 4.0
_MONEYLINE_DIVERGENCE_PROB = 0.15


class HealthIssue(NamedTuple):
    check: str
    detail: str


async def check_source_freshness(db: AsyncSession) -> list[HealthIssue]:
    settings = get_settings()
    keys = list(_SINGLE_RUN_SOURCES) + [
        f"{source}_{sport}"
        for source in _MULTI_SPORT_SOURCES
        for sport in settings.supported_sports
    ]
    now = utcnow()
    issues: list[HealthIssue] = []
    for key in keys:
        base_source = key if key in _SINGLE_RUN_SOURCES else key.rsplit("_", 1)[0]
        interval = _SOURCE_INTERVALS[base_source]

        latest = await db.scalar(
            select(IngestionRun)
            .where(IngestionRun.source == key)
            .order_by(desc(IngestionRun.started_at))
            .limit(1)
        )
        if latest is None:
            # Never run yet (e.g. fresh deploy, before the first beat tick)
            # - nothing to compare freshness against.
            continue
        if latest.status == "failed":
            issues.append(HealthIssue(key, f"latest run failed: {latest.detail}"))
            continue
        if latest.finished_at is None:
            continue  # still running

        age_seconds = (now - latest.finished_at).total_seconds()
        if age_seconds > interval * _STALE_MULTIPLIER:
            issues.append(
                HealthIssue(
                    key,
                    f"no successful run in {age_seconds / 60:.0f} min "
                    f"(expected every {interval / 60:.0f})",
                )
            )
    return issues


async def check_price_divergence(db: AsyncSession, sport: str) -> list[HealthIssue]:
    stmt = (
        select(TeamMarketLine, Game)
        .join(Game, TeamMarketLine.game_id == Game.id)
        .where(Game.sport == sport, TeamMarketLine.market.in_(("spread", "moneyline")))
        .distinct(
            TeamMarketLine.game_id, TeamMarketLine.market, TeamMarketLine.side, TeamMarketLine.source
        )
        .order_by(
            TeamMarketLine.game_id,
            TeamMarketLine.market,
            TeamMarketLine.side,
            TeamMarketLine.source,
            desc(TeamMarketLine.observed_at),
        )
    )
    rows = (await db.execute(stmt)).all()

    grouped: dict[tuple, dict[str, TeamMarketLine]] = {}
    for line, _game in rows:
        key = (line.game_id, line.market, line.side)
        grouped.setdefault(key, {})[line.source] = line

    issues: list[HealthIssue] = []
    for (game_id, market, side), by_source in grouped.items():
        if len(by_source) < 2:
            continue
        if market == "spread":
            values = {src: ln.line for src, ln in by_source.items() if ln.line is not None}
            if len(values) < 2:
                continue
            gap = max(values.values()) - min(values.values())
            if gap > _SPREAD_DIVERGENCE_POINTS:
                issues.append(
                    HealthIssue(
                        "divergence",
                        f"{sport} game {game_id} spread/{side}: {values} differ by {gap:.1f} points",
                    )
                )
        else:  # moneyline
            probs = {
                src: american_to_implied(ln.price_american)
                for src, ln in by_source.items()
                if ln.price_american is not None
            }
            if len(probs) < 2:
                continue
            gap = max(probs.values()) - min(probs.values())
            if gap > _MONEYLINE_DIVERGENCE_PROB:
                issues.append(
                    HealthIssue(
                        "divergence",
                        f"{sport} game {game_id} moneyline/{side}: {probs} differ by {gap:.2f}",
                    )
                )
    return issues


async def run_health_checks(db: AsyncSession) -> list[HealthIssue]:
    issues = await check_source_freshness(db)
    for sport in get_settings().supported_sports:
        issues += await check_price_divergence(db, sport)
    return issues
