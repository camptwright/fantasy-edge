"""Celery application and conservative NFL ingestion schedule."""

from __future__ import annotations

from celery import Celery

from config.settings import get_settings

settings = get_settings()
celery_app = Celery("fantasy_edge", broker=settings.redis_url, include=["src.scheduler.tasks"])
celery_app.conf.update(
    timezone="America/Chicago",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    beat_schedule={
        "sync-espn-scoreboard": {"task": "fantasy.sync_espn", "schedule": 900.0},
        # MLB's and NHL's own primary schedule/score sources
        # (config/settings.py's espn_sports excludes both from
        # sync-espn-scoreboard above) - same 15-minute cadence, no key/
        # quota to be conservative about.
        "sync-mlb-schedule": {"task": "fantasy.sync_mlb", "schedule": 900.0},
        "sync-nhl-schedule": {"task": "fantasy.sync_nhl", "schedule": 900.0},
        "sync-underdog-props": {"task": "fantasy.sync_underdog", "schedule": 900.0},
        # The Odds API task itself no-ops until an API key is configured and
        # applies its durable quota guard before making another request.
        "sync-team-markets": {"task": "fantasy.sync_team_markets", "schedule": 1800.0},
        "sync-sleeper-leagues": {"task": "fantasy.sync_sleeper", "schedule": 900.0},
        # Scraped sources (see the scraping build-out plan): same 30-minute
        # cadence as sync-team-markets - polite pacing per source, not
        # quota-bound like The Odds API, but no reason to poll harder than
        # a team-market line actually moves.
        "sync-pinnacle": {"task": "fantasy.sync_pinnacle", "schedule": 1800.0},
        "sync-bovada": {"task": "fantasy.sync_bovada", "schedule": 1800.0},
        # PrizePicks' single request returns every sport's projections in
        # one ~30MB payload - the same 30-minute cadence, not the props-
        # relevant-sounding 900s Underdog uses, since there is nothing
        # time-sensitive enough here to justify doubling that bandwidth.
        "sync-prizepicks": {"task": "fantasy.sync_prizepicks", "schedule": 1800.0},
        # Health check, not a data source - runs less often than any
        # individual poller since it only needs to catch a source going
        # stale or two books diverging, not react in real time.
        "check-data-health": {"task": "fantasy.check_data_health", "schedule": 3600.0},
        # A real generation call through this stack's local Ollama model
        # takes ~78s (verified live 2026-09-04, no GPU acceleration for a
        # 9B model on this Mac mini) - same 30-minute cadence as the odds
        # sources it narrates over, not faster.
        "generate-recommendations": {"task": "fantasy.generate_recommendations", "schedule": 1800.0},
    },
)
