"""Full-pool grading: freeze Sleeper for every projected player, grade challengers on box scores."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from src.ingest.identity import resolve_team
from src.models.facts import Game, PlayerGameStat, PlayerSnapCount
from src.models.identity import Player
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services import espn_projections, projection_engine_prospective as pep, sleeper_pool as sp

HALF = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}


def test_pairing_scores_every_source_with_each_league_and_averages_the_consensus():
    key = ("g", "p")
    sleeper = {key: {"stats": {"rec": 6, "rec_yd": 70, "rec_td": 0.5}, "position": "WR", "week": 6}}
    espn = {key: {"stats": {"rec": 4, "rec_yd": 50, "rec_td": 0.3}, "keys": "sleeper"}}
    engine = {key: {"stats": {"receptions": 5, "receiving_yards": 60, "receiving_touchdowns": 0.4}, "keys": "internal"}}
    actual = {key: {"receptions": 8, "receiving_yards": 100, "receiving_touchdowns": 1}}
    rows = sp.pair_rows(sleeper, {"espn": espn, "engine_v1": engine}, actual, [NS(league_id="L", scoring_settings=HALF)])
    s, e, g = 3 + 7 + 3, 2 + 5 + 1.8, 2.5 + 6 + 2.4
    assert rows["espn"][0]["engine"] == round(e, 2) and rows["espn"][0]["sleeper"] == round(s, 2)
    assert rows["engine_v1"][0]["engine"] == round(g, 2) and rows["espn"][0]["actual"] == 20.0
    assert rows["consensus"][0]["engine"] == round((s + e + g) / 3, 2)
    # A row missing from any challenger is left out of every list, so all are paired on the same rows.
    assert sp.pair_rows(sleeper, {"espn": {}, "engine_v1": engine}, actual, [NS(league_id="L", scoring_settings=HALF)]) == {}


async def test_capture_freezes_every_projected_player_and_report_grades_on_box_scores(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "archive_root", lambda: tmp_path / "pool")
    monkeypatch.setattr(pep, "archive_root", lambda: tmp_path)
    det, gb = await resolve_team(db, "Detroit Lions"), await resolve_team(db, "Green Bay Packers")
    det.nflverse_abbr, gb.nflverse_abbr = "DET", "GB"
    now = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)
    game = Game(sport="nfl", season=2026, week=6, game_type="REG", status="scheduled",
                game_time=now + timedelta(hours=2), home_team_id=det.id, away_team_id=gb.id)
    later = Game(sport="nfl", season=2026, week=6, game_type="REG", status="scheduled",
                 game_time=now + timedelta(hours=8), home_team_id=gb.id, away_team_id=det.id)
    rostered, unrostered = Player(sport="nfl", full_name="Star Receiver", position="WR"), Player(sport="nfl", full_name="Waiver Back", position="RB")
    db.add_all([game, later, rostered, unrostered,
                SleeperLeague(league_id="L1", platform="sleeper", sport="nfl", name="L", season="2026", status="in_season",
                              roster_positions=[], settings={}, scoring_settings=HALF, raw={})])
    await db.flush()
    db.add_all([SleeperLeagueSnapshot(league_id="L1", week=6, kind="projections", synced_at=now - timedelta(minutes=10), payload={
                    "1": {"gp": 1, "rec": 6, "rec_yd": 70, "rec_td": 0.5, "pts_ppr": 19}, "2": {"gp": 1, "rush_yd": 40, "rush_td": 0.3},
                    "3": {"gp": 0, "rec": 0}, "4": {"adp_dd_ppr": 1000}}),
                SleeperLeagueSnapshot(league_id="L1", week=0, kind="player_metadata", synced_at=now - timedelta(hours=1), payload={
                    "1": {"team": "DET", "position": "WR"}, "2": {"team": "GB", "position": "RB"},
                    "3": {"team": "DET", "position": "WR"}, "4": {"team": "DET", "position": "K"}})])
    await db.commit()

    async def resolve(db, platform, ids):
        return {"1": rostered, "2": unrostered, "3": rostered}

    monkeypatch.setattr(sp, "resolve_platform_players", resolve)
    out = await sp.capture(db, now=now)
    assert out["captured"] == 2 and out["skipped"] == {"not_projected_to_play": 1}
    assert (await sp.capture(db, now=now + timedelta(minutes=30)))["captured"] == 0  # create-only
    frozen = sp.frozen()
    record = frozen[(str(game.id), str(rostered.id))]
    assert record["stats"] == {"gp": 1.0, "rec": 6.0, "rec_yd": 70.0, "rec_td": 0.5}  # no pts_/adp_ keys

    # Challengers frozen pregame for both players; the game finishes; box scores arrive.
    version = pep.version()
    for p, stats in ((rostered, {"receptions": 5, "receiving_yards": 60, "receiving_touchdowns": 0.4}),
                     (unrostered, {"rushing_yards": 50, "rushing_touchdowns": 0.4})):
        (tmp_path / "forecasts").mkdir(exist_ok=True)
        (tmp_path / "forecasts" / f"{p.id}.json").write_text(json.dumps({
            "version": version, "captured_at": (now - timedelta(days=1)).isoformat(), "kickoff": game.game_time.isoformat(),
            "game_id": str(game.id), "player_id": str(p.id), "stats": stats}))
    monkeypatch.setattr(espn_projections, "frozen", lambda: {
        (str(game.id), str(rostered.id)): {"stats": {"rec": 4, "rec_yd": 50, "rec_td": 0.3}},
        (str(game.id), str(unrostered.id)): {"stats": {"rush_yd": 45, "rush_td": 0.2}}})
    game.status = "final"
    db.add_all([PlayerGameStat(player_id=rostered.id, game_id=game.id, stat_type="receptions", value=8),
                PlayerGameStat(player_id=rostered.id, game_id=game.id, stat_type="receiving_yards", value=100),
                PlayerSnapCount(player_id=unrostered.id, game_id=game.id, team_id=gb.id, offense_snaps=20, offense_pct=0.3,
                                source="nflverse", observed_at=now + timedelta(days=2))])
    await db.commit()
    report = await sp.report(db)
    assert report["statuses"]["played"] == 2  # the snap-only back scored 0 and still counts
    rows = report["tracks"]["consensus"]["all_paired"]
    assert rows["n"] == 2 and rows["weeks"] == [6]
    assert report["serving_promoted"] is False and "needs_6_graded_weeks_has_1" in report["tracks"]["espn"]["promotion"]["blockers"]
