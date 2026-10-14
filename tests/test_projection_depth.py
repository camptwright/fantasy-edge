"""Depth-chart/status adjustment, engine research in the fantasy snapshot, depth archive."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import depth_archive
from src.services.fantasy_decision_models import engine_research
from src.services.projection_depth import LONG_TERM, REFILL, DepthStatus, adjust
from src.services.projection_engine import Projection
from src.services.projection_engine_serving import fallback_environment

NOW = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)
GAME, TEAM, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def proj(position, targets=0.0, carries=0.0, attempts=0.0, team_pass=35.0, team_carries=25.0):
    pid = uuid.uuid4()
    stats = {"targets": targets, "receptions": targets * 0.6, "receiving_yards": targets * 8,
             "rushing_attempts": carries, "rushing_yards": carries * 4,
             "passing_attempts": attempts, "passing_yards": attempts * 7, "fumbles_lost": 0.1}
    return Projection(pid, GAME, TEAM, position, stats, 8, team_pass, team_carries, 22.0)


def depth(order=1, *, team=TEAM, status="Active", injury=None, pos="WR"):
    return DepthStatus(team, status, injury, pos, order)


def test_injured_moved_and_off_chart_players_are_removed_unknown_kept():
    out_wr, moved, deep, charted, unknown = (proj("WR", 5), proj("WR", 4), proj("WR", 3),
                                             proj("WR", 6), proj("WR", 2))
    projections = {p.player_id: p for p in (out_wr, moved, deep, charted, unknown)}
    status = {out_wr.player_id: depth(injury="Out"), moved.player_id: depth(team=OTHER),
              deep.player_id: depth(None), charted.player_id: depth(1)}
    adjusted, removed = adjust(projections, status)
    assert removed == {out_wr.player_id: "unavailable", moved.player_id: "moved_team",
                       deep.player_id: "off_depth_chart"}
    assert set(adjusted) == {charted.player_id, unknown.player_id}


def test_a_missing_chart_never_empties_a_position():
    a, b = proj("TE", 4), proj("TE", 3)
    adjusted, removed = adjust({a.player_id: a, b.player_id: b},
                               {a.player_id: depth(None, pos=None)})
    assert not removed and set(adjusted) == {a.player_id, b.player_id}


def test_qbs_are_untouched_unless_the_projected_starter_is_gone():
    starter, backup = proj("QB", attempts=34), proj("QB", attempts=4, carries=1)
    both = {starter.player_id: starter, backup.player_id: backup}
    healthy, _ = adjust(both, {starter.player_id: depth(1, pos="QB"), backup.player_id: depth(2, pos="QB")})
    assert healthy[starter.player_id].stats["passing_attempts"] == pytest.approx(34)
    assert healthy[backup.player_id].stats["passing_attempts"] == pytest.approx(4)  # not zeroed (2026-10-14)
    out, _ = adjust(both, {starter.player_id: depth(1, pos="QB", injury="IR"), backup.player_id: depth(2, pos="QB")})
    assert out[backup.player_id].stats["passing_attempts"] == pytest.approx(34)
    assert out[backup.player_id].stats["passing_yards"] == pytest.approx(34 * 7)
    doubtful, _ = adjust(both, {starter.player_id: depth(1, pos="QB", injury="Doubtful"), backup.player_id: depth(2, pos="QB")})
    assert doubtful[starter.player_id].stats["passing_attempts"] == pytest.approx(34)  # conditional on playing
    assert doubtful[backup.player_id].stats["passing_attempts"] == pytest.approx(34)


def test_backups_pass_nothing_only_when_the_chart_and_last_start_agree():
    starter, backup = proj("QB", attempts=34), proj("QB", attempts=30, carries=1)
    both = {starter.player_id: starter, backup.player_id: backup}
    chart = {starter.player_id: depth(1, pos="QB"), backup.player_id: depth(2, pos="QB")}
    agreed, _ = adjust(both, chart, starters={TEAM: starter.player_id})
    assert agreed[starter.player_id].stats["passing_attempts"] == pytest.approx(34)
    assert agreed[backup.player_id].stats["passing_attempts"] == 0
    assert agreed[backup.player_id].stats["rushing_attempts"] == pytest.approx(1)
    # The backup started last week (e.g. the starter just returned): starter uncertain, both kept.
    disputed, _ = adjust(both, chart, starters={TEAM: backup.player_id})
    assert disputed[backup.player_id].stats["passing_attempts"] == pytest.approx(30)
    assert adjust(both, chart)[0][backup.player_id].stats["passing_attempts"] == pytest.approx(30)
    # Last week's starter is ruled out: the depth-two QB inherits and the third QB passes nothing.
    third = proj("QB", attempts=25)
    three = {**both, third.player_id: third}
    chart3 = {**chart, starter.player_id: depth(1, pos="QB", injury="Out"), third.player_id: depth(3, pos="QB")}
    heir, _ = adjust(three, chart3, starters={TEAM: starter.player_id})
    assert heir[backup.player_id].stats["passing_attempts"] == pytest.approx(34)
    assert heir[third.player_id].stats["passing_attempts"] == 0


def test_last_starters_is_the_most_attempts_in_each_team_latest_game():
    from src.services.projection_depth import last_starters
    a, b = uuid.uuid4(), uuid.uuid4()
    g1, g2 = uuid.uuid4(), uuid.uuid4()
    teams = {(g1, TEAM): SimpleNamespace(game_id=g1, team_id=TEAM, kickoff=NOW - timedelta(days=14)),
             (g2, TEAM): SimpleNamespace(game_id=g2, team_id=TEAM, kickoff=NOW - timedelta(days=7))}
    players = {(a, g1): SimpleNamespace(player_id=a, game_id=g1, team_id=TEAM, stats={"passing_attempts": 35}),
               (a, g2): SimpleNamespace(player_id=a, game_id=g2, team_id=TEAM, stats={"passing_attempts": 6}),
               (b, g2): SimpleNamespace(player_id=b, game_id=g2, team_id=TEAM, stats={"passing_attempts": 28})}
    history = SimpleNamespace(teams=teams, players=players, positions={a: "QB", b: "QB"})
    assert last_starters(history, NOW) == {TEAM: b}
    assert last_starters(history, NOW - timedelta(days=10)) == {TEAM: a}


def test_vacated_volume_is_shared_in_proportion_without_a_team_cap():
    # No cap: 40 projected targets against a 31.5 team total stay 40 (the cap scaled starters down).
    a, b, c = proj("WR", 25), proj("WR", 15), proj("TE", 5)
    adjusted, _ = adjust({a.player_id: a, b.player_id: b}, {})
    assert sum(p.stats["targets"] for p in adjusted.values()) == pytest.approx(40)
    # The ruled-out starter's targets go to the others in proportion to their own, times REFILL.
    adjusted, removed = adjust({p.player_id: p for p in (a, b, c)}, {a.player_id: depth(injury="Out")})
    assert removed == {a.player_id: "unavailable"}
    assert adjusted[b.player_id].stats["targets"] == pytest.approx(15 * (1 + REFILL * 25 / 20))
    assert adjusted[c.player_id].stats["receiving_yards"] == pytest.approx(adjusted[c.player_id].stats["targets"] * 8)
    # A Doubtful player keeps his own projection (conditional on playing) and also vacates his volume.
    adjusted, removed = adjust({p.player_id: p for p in (a, b)}, {a.player_id: depth(injury="Doubtful")})
    assert not removed and adjusted[a.player_id].stats["targets"] == pytest.approx(25)
    assert adjusted[b.player_id].stats["targets"] == pytest.approx(15 * (1 + REFILL * 25 / 15))
    # A long-term status removes the player without passing his volume on (teammates already absorb it).
    adjusted, _ = adjust({p.player_id: p for p in (a, b)}, {a.player_id: depth(injury="IR")})
    assert adjusted[b.player_id].stats["targets"] == pytest.approx(15)
    # Later weeks: nothing vacates.
    adjusted, _ = adjust({p.player_id: p for p in (a, b)}, {a.player_id: depth(injury="Doubtful")}, LONG_TERM, set())
    assert adjusted[b.player_id].stats["targets"] == pytest.approx(15)


def test_later_weeks_ignore_a_one_game_out_designation():
    a = proj("RB", carries=15)
    status = {a.player_id: depth(1, pos="RB", injury="Out")}
    assert adjust({a.player_id: a}, status)[1]
    assert not adjust({a.player_id: a}, status, LONG_TERM)[1]


def test_unlined_games_use_the_team_recent_implied_mean():
    rows = [SimpleNamespace(team_id=TEAM, implied_points=v, kickoff=NOW - timedelta(days=i))
            for i, v in enumerate([20, 24, None])]
    assert fallback_environment(rows, TEAM, 22.0) == pytest.approx(22.0)
    assert fallback_environment(rows, OTHER, 21.5) == 21.5


def league(platform="sleeper"):
    return SimpleNamespace(platform=platform, scoring_settings={"rec": 1, "rec_yd": 0.1, "rush_yd": 0.1})


def checkpoint(generated_at, weeks):
    return {"status": "research", "generated_at": generated_at.isoformat(), "engine_version": "v",
            "games": {"g6": {"environment": "market_line"}, "g7": {"environment": "team_average_no_line"}},
            "players": {"c1": weeks}}


def player(pid="s1", games=("g6", "g7")):
    return {"player_id": pid, "position": "WR", "next_games": [
        {"id": g, "kickoff": (NOW + timedelta(days=i + 1)).isoformat()} for i, g in enumerate(games)]}


def test_engine_research_scores_with_league_weights_and_sums_only_unstarted_games():
    weeks = {"6": {"game_id": "g6", "stats": {"receptions": 5, "receiving_yards": 60}},
             "7": {"game_id": "g7", "stats": {"receptions": 4, "receiving_yards": 50}}}
    p = player()
    engine_research([p], {"s1": SimpleNamespace(id="c1")}, checkpoint(NOW - timedelta(minutes=10), weeks), league(), 6, NOW)
    e = p["engine"]
    assert e["week_points"] == 11.0 and e["ros_points"] == 20.0 and e["ros_games"] == 2
    assert e["ros_lined_games"] == 1 and e["serving_promoted"] is False
    started = player(games=("g7",))  # g6 kicked off: excluded, not zero
    engine_research([started], {"s1": SimpleNamespace(id="c1")}, checkpoint(NOW - timedelta(minutes=10), weeks), league(), 6, NOW)
    assert started["engine"]["week_points"] is None and started["engine"]["ros_points"] == 9.0


@pytest.mark.parametrize("case", ["stale", "missing", "kicker", "unresolved"])
def test_engine_research_is_missing_not_zero(case):
    p = player() if case != "kicker" else {**player(), "position": "K"}
    cp = None if case == "missing" else checkpoint(NOW - (timedelta(hours=4) if case == "stale" else timedelta(0)), {})
    resolved = {} if case == "unresolved" else {"s1": SimpleNamespace(id="c1")}
    engine_research([p], resolved, cp, league(), 6, NOW)
    assert "points" not in json.dumps(p["engine"])


def test_depth_archive_is_daily_and_first_observation_wins(tmp_path):
    catalog = {"1": {"position": "QB", "team": "KC", "depth_chart_order": 1, "status": "Active"},
               "2": {"position": "K", "team": "KC"}}
    assert depth_archive.archive_daily(catalog, NOW, tmp_path)
    catalog["1"]["depth_chart_order"] = 2
    assert not depth_archive.archive_daily(catalog, NOW + timedelta(hours=3), tmp_path)
    saved = json.loads((tmp_path / "sleeper-depth-status" / "20261012.json").read_text())
    assert saved["players"] == {"1": {**dict.fromkeys(depth_archive.FIELDS), "position": "QB", "team": "KC",
                                      "depth_chart_order": 1, "status": "Active"}}
