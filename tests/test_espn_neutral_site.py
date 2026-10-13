from types import SimpleNamespace

from src.ingest.espn import _apply_schedule_fields


def game():
    return SimpleNamespace(season=2026, week=None, game_type=None, game_time=None, status="scheduled", neutral_site=False)


def event(**competition):
    return {"season": {"year": 2026, "type": 2}, "week": {"number": 7}, "date": "2026-10-18T13:30Z",
            "competitions": [competition]}


def test_neutral_site_follows_espn_and_survives_a_poll_without_the_flag():
    g = game()
    e = event(neutralSite=True, status={"type": {"state": "pre"}})
    _apply_schedule_fields(g, e, e["competitions"][0], "nfl")
    assert g.neutral_site is True
    e = event(status={"type": {"state": "pre"}})
    _apply_schedule_fields(g, e, e["competitions"][0], "nfl")
    assert g.neutral_site is True  # missing key keeps the last observed value
    e = event(neutralSite=False, status={"type": {"state": "post"}})
    _apply_schedule_fields(g, e, e["competitions"][0], "nfl")
    assert g.neutral_site is False and g.status == "final"
