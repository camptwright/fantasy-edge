"""Celery app + beat schedule.

Every entry here is a fixed-interval "tick" task, even the season-aware Odds
API polling (constraint #4). A season-aware *beat schedule* (different
crontabs active in different months) would need either a custom Scheduler
class or redeploying config at season boundaries; instead `odds_tick` fires
on a short fixed interval and decides internally, per sport, whether enough
time has passed for THAT sport's current season_months/interval - the
literal schedule is boring and static, and all of constraint #4's logic
lives in one place (`tasks.odds_tick`) instead of being split between beat
config and task code.
"""

from __future__ import annotations

from celery import Celery

from config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "fantasy_edge",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.scheduler.tasks"],
)

celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.task_track_started = True
# worker_prefetch_multiplier=1: this workload is a handful of periodic ticks
# and event-triggered evaluations, not a high-throughput queue - the default
# prefetch-4 just means one slow tick (an Underdog fetch) delays unrelated
# work sitting behind it in the same worker process for no benefit.
celery_app.conf.worker_prefetch_multiplier = 1

celery_app.conf.beat_schedule = {
    "game-sync-tick": {
        "task": "src.scheduler.tasks.game_sync_tick",
        "schedule": 300.0,
    },
    "props-tick": {
        "task": "src.scheduler.tasks.props_tick",
        "schedule": float(settings.props_poll_interval),
    },
    "odds-tick": {
        # Fires often; tasks.odds_tick is a no-op per sport until that
        # sport's own season-aware interval has actually elapsed.
        "task": "src.scheduler.tasks.odds_tick",
        "schedule": 60.0,
    },
    "value-agent-tick": {
        "task": "src.scheduler.tasks.value_agent_tick",
        "schedule": 900.0,
    },
    "clv-tracker-tick": {
        "task": "src.scheduler.tasks.clv_tracker_tick",
        "schedule": 6 * 3600.0,
    },
}
