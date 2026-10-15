"""Celery application and conservative NFL ingestion schedule."""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from config.settings import get_settings

settings = get_settings()
# httpx's INFO access logs include complete query strings. Several upstream
# APIs authenticate by query parameter, so those logs must not reach worker
# output where secrets could be retained by a terminal or log collector.
logging.getLogger("httpx").setLevel(logging.WARNING)
celery_app = Celery("fantasy_edge", broker=settings.redis_url, include=["src.scheduler.tasks", "src.scheduler.calibration", "src.scheduler.audit_work"])
celery_app.conf.update(
    timezone="America/Chicago",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    worker_prefetch_multiplier=1,
    task_routes={name: {"queue": "evaluation"} for name in (
        "fantasy.evaluate_models", "fantasy.grade_forecasts", "fantasy.refresh_missing_results",
        "fantasy.refresh_fantasy_models", "fantasy.projection_engine_research", "fantasy.projection_engine_v2",
        "fantasy.compress_raw_archive")},
    beat_schedule={
        "observe-operations": {"task":"fantasy.observe_operations","schedule":300.0},
        "refresh-fantasy-models": {"task":"fantasy.refresh_fantasy_models","schedule":60.0},
        "refresh-missing-results": {"task":"fantasy.refresh_missing_results","schedule":1800.0},
        "research-shadow": {"task":"fantasy.research_shadow","schedule":900.0},
        "register-nfl-lab": {"task":"fantasy.register_nfl_lab","schedule":900.0},
        "refresh-nfl-stats": {"task":"fantasy.refresh_nfl_stats","schedule":86400.0},
        "refresh-snap-counts": {"task":"fantasy.refresh_snap_counts","schedule":86400.0},
        "projection-engine-research": {"task":"fantasy.projection_engine_research","schedule":1800.0},
        "projection-engine-v2": {"task":"fantasy.projection_engine_v2","schedule":7200.0},
        "raw-retention-report": {"task":"fantasy.raw_retention_report","schedule":86400.0},
        "compress-raw-archive": {"task":"fantasy.compress_raw_archive","schedule":3600.0},
        "archive-rosters": {"task": "fantasy.archive_rosters", "schedule": 21600.0},
        "sync-fantasy-market": {"task":"fantasy.sync_fantasy_market","schedule":86400.0},
        "archive-event-weather": {"task":"fantasy.archive_event_weather","schedule":3600.0},
        "full-nfl-schedule": {"task":"fantasy.full_nfl_schedule","schedule":86400.0},
        "fantasy-scoring": {"task":"fantasy.fantasy_scoring","schedule":21600.0},
        "fantasy-prospective": {"task":"fantasy.fantasy_prospective","schedule":900.0},
        "fantasy-retention-research": {"task":"fantasy.retention_research","schedule":1800.0},
        "fantasy-specialist-research": {"task":"fantasy.specialist_research","schedule":1800.0},
        "capture-ledger-closes": {"task":"fantasy.capture_ledger_closes","schedule":300.0},
        "retry-team-ratings": {"task": "fantasy.retry_team_ratings", "schedule": 3600.0},
        "sync-aggregate-props": {"task": "fantasy.sync_aggregate_props", "schedule": 300.0},
        "prop-board": {"task": "fantasy.prop_board", "schedule": 600.0},
        "validate-active-slate": {"task": "fantasy.validate_active_slate", "schedule": 1800.0},
        "expand-ncaaf-prop-history": {"task": "fantasy.expand_ncaaf_props", "schedule": 3600.0},
        "sync-nfl-player-results": {"task": "fantasy.sync_nfl_results", "schedule": 1800.0},
        "sync-ncaaf-player-results": {"task": "fantasy.sync_ncaaf_results", "schedule": 1800.0},
        "grade-live-forecasts": {"task": "fantasy.grade_forecasts", "schedule": 1800.0},
        "sync-nba-player-results": {"task": "fantasy.sync_nba_results", "schedule": 3600.0},
        "capture-live-forecasts": {"task": "fantasy.capture_forecasts", "schedule": 900.0},
        "player-lab-prospective": {"task": "fantasy.player_lab_prospective", "schedule": 900.0},
        "college-lab-prospective": {"task": "fantasy.college_lab_prospective", "schedule": 900.0},
        "sync-nhl-player-results": {"task": "fantasy.sync_nhl_results", "schedule": 3600.0},
        "sync-mlb-player-results": {"task": "fantasy.sync_mlb_results", "schedule": 3600.0},
        "evaluate-model-candidates": {"task": "fantasy.evaluate_models", "schedule": crontab(minute=10)},
        "archive-news-evidence": {"task": "fantasy.archive_news", "schedule": 3600.0},
        "archive-espn-injury-evidence": {"task": "fantasy.archive_espn_injuries", "schedule": 900.0},
        "archive-mlb-availability": {"task": "fantasy.archive_mlb_availability", "schedule": 1800.0},
        "archive-football-availability": {"task": "fantasy.archive_football_availability", "schedule": 1800.0},
        "sync-espn-scoreboard": {"task": "fantasy.sync_espn", "schedule": 300.0},
        # MLB's and NHL's own primary schedule/score sources
        # (config/settings.py's espn_sports excludes both from
        # sync-espn-scoreboard above) - same 5-minute cadence, no key/
        # quota to be conservative about.
        "sync-mlb-schedule": {"task": "fantasy.sync_mlb", "schedule": 300.0},
        "sync-nhl-schedule": {"task": "fantasy.sync_nhl", "schedule": 300.0},
        # Replaced by quota-controlled aggregate feeds; direct endpoint requires upgrade.
        # The Odds API task itself no-ops until an API key is configured and
        # applies its durable quota guard before making another request.
        "sync-team-markets": {"task": "fantasy.sync_team_markets", "schedule": 1800.0},
        "sync-sleeper-leagues": {"task": "fantasy.sync_sleeper", "schedule": 900.0},
        # No-ops until ESPN_LEAGUE_IDS/ESPN_S2/ESPN_SWID are configured -
        # see fantasy.sync_espn_fantasy's own guard.
        "sync-espn-fantasy-leagues": {"task": "fantasy.sync_espn_fantasy", "schedule": 900.0},
        # Scraped sources (see the scraping build-out plan): same 30-minute
        # cadence as sync-team-markets - polite pacing per source, not
        # quota-bound like The Odds API, but no reason to poll harder than
        # a team-market line actually moves.
        "sync-pinnacle": {"task": "fantasy.sync_pinnacle", "schedule": 1800.0},
        "sync-bovada": {"task": "fantasy.sync_bovada", "schedule": 1800.0},
        # PrizePicks scraping is prohibited by this repository's policy.
        # Health check, not a data source - runs less often than any
        # individual poller since it only needs to catch a source going
        # stale or two books diverging, not react in real time.
        "check-data-health": {"task": "fantasy.check_data_health", "schedule": 3600.0},
        # A real generation call through this stack's local Ollama model
        # takes ~78s (verified live 2026-09-04, no GPU acceleration for a
        # 9B model on this Mac mini) - same 30-minute cadence as the odds
        # sources it narrates over, not faster.
        "generate-recommendations": {"task": "fantasy.generate_recommendations", "schedule": 1800.0},
        # Daily digest, not every 30-min generation cycle - see
        # post_narrative_to_dashboard's own docstring in tasks.py for why.
        "post-narrative-to-dashboard": {
            "task": "fantasy.post_narrative_to_dashboard",
            "schedule": crontab(hour=8, minute=0),
        },
    },
)


@worker_ready.connect
def catch_up_evaluation(sender=None, **kwargs):
    if sender is not None:
        sender.app.send_task('fantasy.evaluate_models')
