"""Projection-engine Phase 1 inputs: snap counts, usage shares, implied totals."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from src.ingest.nflverse import ingest_games
from src.ingest.players import ingest_player_stats, ingest_players
from src.ingest.usage import ingest_snap_counts
from src.models.facts import Game, PlayerSnapCount, TeamMarketLine
from src.services.game_environment import environments, implied_points
from src.services.player_usage import season_usage, shares, team_snaps

GAME = "2025_01_KC_LAC"
PLAYERS = [
    dict(gsis_id="00-0033873", pfr_id="MahoPa00", display_name="Patrick Mahomes", position="QB"),
    dict(gsis_id="00-kelce", pfr_id="KelcTr00", display_name="Travis Kelce", position="TE"),
    dict(gsis_id="00-rice", pfr_id="RiceRa00", display_name="Rashee Rice", position="WR"),
]
SNAPS = [
    dict(game_id=GAME, pfr_player_id="MahoPa00", team="KC", offense_snaps=64, offense_pct=1.0, st_snaps=0),
    dict(game_id=GAME, pfr_player_id="KelcTr00", team="KC", offense_snaps=48, offense_pct=0.75, st_snaps=2),
    dict(game_id=GAME, pfr_player_id="RiceRa00", team="KC", offense_snaps=56, offense_pct=0.88, st_snaps=None),
]


@pytest.fixture(autouse=True)
def nflverse_fixture(monkeypatch):
    from src.ingest import nflverse, players

    provider = SimpleNamespace(
        load_schedules=lambda seasons: [dict(
            game_id=GAME, home_team="LAC", away_team="KC", season=2025, week=1,
            game_type="REG", gameday="2025-09-05", gametime="20:20",
            home_score=21, away_score=24, spread_line=-3.0, total_line=46.5)],
        load_players=lambda: PLAYERS,
        load_player_stats=lambda seasons: [
            dict(player_id="00-0033873", season=2025, week=1, team="KC", season_type="REG",
                 attempts=40, carries=4),
            dict(player_id="00-kelce", season=2025, week=1, team="KC", season_type="REG", targets=10),
            dict(player_id="00-rice", season=2025, week=1, team="KC", season_type="REG",
                 targets=6, carries=0),
        ],
    )
    monkeypatch.setattr(nflverse, "_nflreadpy", lambda: provider)
    monkeypatch.setattr(players, "_nflreadpy", lambda: provider)


async def _seed(db):
    await ingest_games(db, seasons=[2025])
    await ingest_players(db)
    await ingest_player_stats(db, seasons=[2025])


def test_implied_points_follow_the_storage_sign_convention():
    # Home favoured by 3 is stored as home -3: home gets the bigger share.
    assert implied_points(47.0, -3.0) == (25.0, 22.0)
    assert implied_points(47.0, 3.0) == (22.0, 25.0)


def test_team_snaps_recovers_the_team_total_from_rounded_percentages():
    assert team_snaps([(64, 1.0), (48, 0.75), (56, 0.88)]) == 64
    assert team_snaps([]) == 0


def test_shares_divide_by_the_teams_own_volume_and_leave_no_volume_unknown():
    game, team = uuid.uuid4(), uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [dict(player_id=p, game_id=game, team_id=team, offense_snaps=s, offense_pct=pct,
                 season=2025, week=1) for p, s, pct in ((a, 60, 1.0), (b, 30, 0.5))]
    usage = {u.player_id: u for u in shares(rows, {(a, game): {"targets": 3.0},
                                                    (b, game): {"targets": 9.0}})}
    assert usage[b].target_share == pytest.approx(0.75)
    assert usage[a].team_targets == 12.0
    # No carries recorded for the team: share is unknown, not zero.
    assert usage[a].carry_share is None


async def test_snap_counts_resolve_exact_ids_and_skip_unresolvable_rows(db):
    await _seed(db)
    unknown = dict(SNAPS[0], pfr_player_id="Nobody00")
    defensive = dict(SNAPS[1], offense_snaps=0, offense_pct=0.0)
    other_game = dict(SNAPS[2], game_id="2025_01_XX_YY")
    written = await ingest_snap_counts(db, [2025], records=SNAPS + [unknown, defensive, other_game],
                                       players=PLAYERS)
    assert written == 3
    # First observation wins; a rerun writes nothing.
    assert await ingest_snap_counts(db, [2025], records=SNAPS, players=PLAYERS) == 0
    assert await db.scalar(select(func.count()).select_from(PlayerSnapCount)) == 3


async def test_season_usage_joins_snaps_to_stats(db):
    await _seed(db)
    await ingest_snap_counts(db, [2025], records=SNAPS, players=PLAYERS)
    usage = {u.snap_share: u for u in await season_usage(db, 2025)}
    kelce = usage[0.75]
    assert kelce.target_share == pytest.approx(10 / 16)
    assert kelce.team_offense_snaps == 64
    assert kelce.team_pass_attempts == 40


async def test_environment_is_point_in_time_and_same_source(db):
    await _seed(db)
    game = await db.scalar(select(Game).where(Game.nflverse_game_id == GAME))
    kickoff = datetime(2025, 9, 6, 0, 20, tzinfo=timezone.utc)

    def line(market, side, value, source, at):
        return TeamMarketLine(game_id=game.id, market=market, side=side, line=value,
                              source=source, line_type="live", observed_at=at)

    db.add_all([
        line("spread", "home", 2.5, "pinnacle", kickoff - timedelta(days=2)),
        line("total", "over", 45.0, "pinnacle", kickoff - timedelta(days=2)),
        line("spread", "home", 3.5, "pinnacle", kickoff - timedelta(hours=1)),
        # After kickoff: a backtest at kickoff must not see it.
        line("total", "over", 60.0, "pinnacle", kickoff + timedelta(hours=1)),
        # A spread with no same-source total never pairs with pinnacle's total.
        line("spread", "home", -10.0, "bovada", kickoff - timedelta(hours=1)),
    ])
    await db.commit()

    env = (await environments(db, [game.id], as_of=kickoff))[game.id]
    assert env.source == "pinnacle"
    assert (env.total, env.home_spread) == (45.0, 3.5)
    assert (env.home_points, env.away_points) == (20.75, 24.25)

    # Before any line existed: absent, never a league-average default.
    assert await environments(db, [game.id], as_of=kickoff - timedelta(days=3)) == {}
