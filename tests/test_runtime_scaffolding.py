from src.scheduler.celery_app import celery_app


def test_celery_schedule_covers_every_ingestion_source():
    """Was "NFL only" before Sleeper's own scheduled sync existed - that
    scope no longer matches beat_schedule's real contents, which now also
    covers NCAAF via the same three tasks (see src/scheduler/tasks.py, each
    of which loops over settings.supported_sports internally), plus the
    scraped sources (Pinnacle, Bovada, PrizePicks) added alongside The Odds
    API and Underdog as team-market/props sources."""
    scheduled = celery_app.conf.beat_schedule
    assert {item["task"] for item in scheduled.values()} == {
        "fantasy.sync_espn",
        "fantasy.sync_underdog",
        "fantasy.sync_team_markets",
        "fantasy.sync_sleeper",
        "fantasy.sync_pinnacle",
        "fantasy.sync_bovada",
        "fantasy.sync_prizepicks",
        "fantasy.check_data_health",
        "fantasy.sync_mlb",
        "fantasy.sync_nhl",
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
