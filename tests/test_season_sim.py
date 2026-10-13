"""Standings from matchup results and simulated playoff odds."""

import pytest

from src.services import season_sim as ss


def results():
    # week 1: 1 beats 2, 3 beats 4; week 2: 1 beats 3, 4 ties 2
    rows = [(1, 1, "a", 120), (1, 2, "a", 90), (1, 3, "b", 110), (1, 4, "b", 80),
            (2, 1, "c", 130), (2, 3, "c", 100), (2, 2, "d", 95), (2, 4, "d", 95)]
    return [{"week": w, "roster_id": r, "matchup_id": m, "points": p} for w, r, m, p in rows]


def test_standings_count_wins_losses_ties_and_points():
    t = ss.standings(results())
    assert (t[1]["wins"], t[1]["losses"], t[1]["pf"], t[1]["pa"]) == (2, 0, 250.0, 190.0)
    assert (t[2]["ties"], t[4]["ties"], t[4]["losses"]) == (1, 1, 1)


def test_simulation_favours_the_strong_unbeaten_team_and_is_deterministic():
    t = ss.standings(results())
    remaining = [(3, 1, 4), (3, 2, 3), (4, 1, 2), (4, 3, 4)]
    strength = ss.weekly_strength(t, [3, 4])
    odds = ss.simulate(t, remaining, strength, playoff_teams=2, sd=20.0)
    assert odds[1]["playoff_odds"] > 0.95 and odds[4]["playoff_odds"] < 0.2
    assert abs(sum(v["playoff_odds"] for v in odds.values()) - 2.0) < 1e-9  # exactly two seeds per season
    assert odds == ss.simulate(t, remaining, strength, playoff_teams=2, sd=20.0)


def test_weekly_strength_dips_for_a_bye_heavy_week_within_the_clip():
    t = {1: {"pf": 300.0, "games": 3}}
    s = ss.weekly_strength(t, [5, 6], {(1, 5): 50.0, (1, 6): 100.0})
    assert s[(1, 5)] == pytest.approx(100 * 0.75) and s[(1, 6)] == pytest.approx(100 * 1.25)
    assert ss.weekly_strength(t, [5])[(1, 5)] == 100.0  # no projection: points per game


@pytest.mark.asyncio
async def test_standings_endpoint_uses_snapshots_and_schedule(db, monkeypatch):
    from fastapi import Response
    from src.api.routers import workspace
    from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
    db.add(SleeperLeague(league_id="L", sport="nfl", name="Test", season="2026", status="in_season", roster_positions=["QB"],
                         settings={"playoff_teams": 2}, scoring_settings={}, raw={}))
    by_week = {}
    for r in results():
        by_week.setdefault(r["week"], []).append({"roster_id": r["roster_id"], "matchup_id": r["matchup_id"], "points": r["points"]})
    for w, rows in by_week.items():
        db.add(SleeperLeagueSnapshot(league_id="L", week=w, kind="matchups", payload=rows))
    db.add(SleeperLeagueSnapshot(league_id="L", week=3, kind="matchups", payload=[
        {"roster_id": 1, "matchup_id": "e", "points": 0}, {"roster_id": 4, "matchup_id": "e", "points": 0},
        {"roster_id": 2, "matchup_id": "f", "points": 0}, {"roster_id": 3, "matchup_id": "f", "points": 0}]))
    db.add(SleeperLeagueSnapshot(league_id="L", week=4, kind="schedule", payload=[
        {"roster_id": 1, "matchup_id": 1}, {"roster_id": 2, "matchup_id": 1}, {"roster_id": 3, "matchup_id": 2}, {"roster_id": 4, "matchup_id": 2}]))
    await db.commit()

    async def fake_read(_db, _id):
        return {"week": 3, "players": [], "roster_positions": ["QB"],
                "rosters": [{"roster_id": i, "name": f"T{i}", "is_mine": i == 1, "player_ids": []} for i in (1, 2, 3, 4)]}
    monkeypatch.setattr(workspace, "read", fake_read)
    view = await workspace.league_standings("L", Response(), db)
    assert view.status == "research" and view.remaining_games == 4 and view.playoff_teams == 2
    assert [r.name for r in view.rows][:1] == ["T1"] and view.rows[0].is_mine and view.rows[0].playoff_odds > 0.9


@pytest.mark.asyncio
async def test_recap_reports_result_all_play_bench_and_luck(db, monkeypatch):
    from fastapi import Response
    from src.api.routers import workspace
    from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
    db.add(SleeperLeague(league_id="R", sport="nfl", name="Recap", season="2026", status="in_season", roster_positions=["QB", "WR", "BN"],
                         settings={}, scoring_settings={}, raw={}))
    week1 = [{"roster_id": 1, "matchup_id": 1, "points": 100.0, "starters": ["qb", "wr"], "players": ["qb", "wr", "bn"],
              "players_points": {"qb": 70.0, "wr": 30.0, "bn": 45.0}},
             {"roster_id": 2, "matchup_id": 1, "points": 120.0}, {"roster_id": 3, "matchup_id": 2, "points": 90.0},
             {"roster_id": 4, "matchup_id": 2, "points": 60.0}]
    db.add(SleeperLeagueSnapshot(league_id="R", week=1, kind="matchups", payload=week1))
    await db.commit()

    async def fake_read(_db, _id):
        return {"week": 2, "roster_positions": ["QB", "WR", "BN"],
                "players": [{"player_id": "qb", "name": "QB One", "position": "QB"}, {"player_id": "wr", "name": "WR One", "position": "WR"},
                            {"player_id": "bn", "name": "Bench Star", "position": "WR"}],
                "rosters": [{"roster_id": i, "name": f"T{i}", "is_mine": i == 1, "player_ids": []} for i in (1, 2, 3, 4)]}
    monkeypatch.setattr(workspace, "read", fake_read)
    r = await workspace.league_recap("R", Response(), None, db)
    w = r.week
    assert (r.status, w.result, w.opponent, w.score_rank, w.all_play_wins, w.all_play_losses) == ("available", "L", "T2", 2, 2, 1)
    assert (w.top_scorer, w.best_bench, w.bench_points_left, w.league_median) == ("QB One", "Bench Star", 15.0, 95.0)
    assert w.biggest_blowout.home_points == 90.0 and w.low_team == "T4"
    assert (r.season.wins, r.season.expected_wins, r.season.luck) == (0, 0.67, -0.67)  # unlucky: 2-1 all-play, lost
