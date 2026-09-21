from src.scheduler.celery_app import celery_app


def test_live_scores_refresh_without_increasing_paid_odds_polling():
    scheduled = celery_app.conf.beat_schedule
    for name in ('sync-espn-scoreboard', 'sync-mlb-schedule', 'sync-nhl-schedule'):
        assert scheduled[name]['schedule'] == 300.0
    assert scheduled['sync-aggregate-props']['schedule'] == 300.0


def test_celery_schedule_covers_every_ingestion_source():
    """Was "NFL only" before Sleeper's own scheduled sync existed - that
    scope no longer matches beat_schedule's real contents, which now also
    covers NCAAF via the same three tasks (see src/scheduler/tasks.py, each
    of which loops over settings.supported_sports internally), plus the
    scraped sources (Pinnacle, Bovada, PrizePicks) added alongside The Odds
    API and Underdog as team-market/props sources."""
    scheduled = celery_app.conf.beat_schedule
    assert {item["task"] for item in scheduled.values()} == {
        "fantasy.sync_fantasy_market",
        "fantasy.archive_event_weather",
        "fantasy.full_nfl_schedule",
        "fantasy.fantasy_scoring",
        "fantasy.fantasy_prospective",
        "fantasy.capture_ledger_closes",
        "fantasy.retry_team_ratings",
        "fantasy.validate_active_slate",
        "fantasy.sync_espn",
        "fantasy.sync_espn_fantasy",
        "fantasy.sync_aggregate_props",
        "fantasy.sync_team_markets",
        "fantasy.sync_sleeper",
        "fantasy.sync_pinnacle",
        "fantasy.sync_bovada",
        "fantasy.check_data_health",
        "fantasy.sync_mlb",
        "fantasy.sync_nhl",
        "fantasy.generate_recommendations",
        "fantasy.sync_nba_results",
        "fantasy.sync_nhl_results",
        "fantasy.sync_mlb_results",
        "fantasy.sync_ncaaf_results",
        "fantasy.sync_nfl_results",
        "fantasy.expand_ncaaf_props",
        "fantasy.capture_forecasts",
        "fantasy.player_lab_prospective",
        "fantasy.college_lab_prospective",
        "fantasy.post_narrative_to_dashboard",
        "fantasy.grade_forecasts",
        "fantasy.evaluate_models",
        "fantasy.archive_news",
        "fantasy.archive_espn_injuries",
        "fantasy.archive_mlb_availability",
        "fantasy.archive_football_availability",
    }


def test_health_routes_are_registered():
    from fastapi.routing import APIRoute

    from src.api.main import app

    # app.routes mixes plain APIRoute entries (defined directly on `app`)
    # with a lazy include-router entry for the sportsbook router (see
    # app.include_router in src/api/main.py) that has no .path of its own -
    # filter to APIRoute so this doesn't crash on that entry's shape.
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/health" in paths
    assert "/api/health" in paths
