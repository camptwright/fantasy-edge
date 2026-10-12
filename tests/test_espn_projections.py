"""ESPN projections: translation, prospective freezing, consensus fields."""

from datetime import datetime, timedelta, timezone

from src.api.routers import workspace
from src.ingest.identity import resolve_team
from src.models.facts import Game
from src.models.identity import Player, PlayerExternalId
from src.services import espn_projections as ep

WEEK = 6
ESPN_PLAYER = {"id": 3916387, "defaultPositionId": 3, "stats": [
    {"statSourceId": 0, "scoringPeriodId": WEEK, "stats": {"53": 9.0}},
    {"statSourceId": 1, "scoringPeriodId": WEEK, "stats": {"53": 7.0, "41": 7.0, "42": 85.0, "61": 85.0, "43": 0.6, "58": 10.0}}]}


def test_translation_reads_projected_stats_once():
    assert ep.translate(ESPN_PLAYER, WEEK) == {"rec": 7.0, "rec_yd": 85.0, "rec_td": 0.6}
    assert ep.translate(ESPN_PLAYER, WEEK + 1) is None
    assert ep.score({"rec": 7.0, "rec_yd": 85.0, "rec_td": 0.6}, {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6}) == 3.5 + 8.5 + 3.6


async def test_capture_freezes_once_per_game_and_skips_games_outside_the_window(db, tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "archive_root", lambda: tmp_path)
    det, gb = await resolve_team(db, "Detroit Lions"), await resolve_team(db, "Green Bay Packers")
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    db.add(Game(sport="nfl", season=2026, week=WEEK, game_type="REG", status="scheduled",
                game_time=now + timedelta(days=2), home_team_id=det.id, away_team_id=gb.id))
    player = Player(sport="nfl", full_name="Amon-Ra St. Brown", position="WR")
    db.add(player)
    await db.flush()
    db.add(PlayerExternalId(player_id=player.id, source="espn_nfl", external_id="3916387"))
    await db.commit()

    async def fetcher(season, week):
        assert (season, week) == (2026, WEEK)
        return {"3916387": {"position": "WR", "team": "DET", "stats": ep.translate(ESPN_PLAYER, WEEK)}}

    first = await ep.capture(db, now=now, fetcher=fetcher)
    assert (first["status"], first["resolved"], first["captured"]) == ("captured", 1, 1)
    assert (await ep.capture(db, now=now + timedelta(hours=1), fetcher=fetcher))["status"] == "fresh"
    again = await ep.capture(db, now=now + timedelta(hours=4), fetcher=fetcher)
    assert again["captured"] == 0  # first capture wins: frozen once per (game, player)
    frozen = ep.frozen(tmp_path)
    assert len(frozen) == 1 and next(iter(frozen.values()))["stats"]["rec"] == 7.0
    latest = await ep.latest(db)
    assert latest["week"] == WEEK and str(player.id) in latest["players"]


def test_consensus_needs_two_sources_and_never_zero_fills():
    base = {"weekly_points": 14.0, "_espn_points": 12.0, "engine": {"status": "research", "week_points": 16.0}}
    assert workspace.consensus_detail(base) == {"espn_week_points": 12.0, "consensus_sources": 3, "consensus_week_points": 14.0}
    only = workspace.consensus_detail({"weekly_points": 14.0, "engine": {"status": "missing_or_stale_engine_research"}})
    assert only == {"espn_week_points": None, "consensus_sources": 1, "consensus_week_points": None}
