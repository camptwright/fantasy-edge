"""Projection engine v1: game environment -> team volume -> usage share -> efficiency.

The industry recipe (PFF, ESPN/Mike Clay, Yahoo's BAKER, WalterPicks; see
docs/2026-10-06-overhaul-status-and-ui-direction.md), built only from data
this app already stores:

1. Team volume. Pass attempts and carries are fitted, pooled across all
   prior team-games, as a linear function of the team's own recent volume,
   its implied points and its spread (game script: trailing teams throw).
   Coefficients come from history before the cutoff, never hand-set.
2. Usage share. A player's target/carry/pass-attempt share of his team's
   volume, exponentially weighted toward recent games and shrunk toward a
   small prior so one big game cannot become a 40% share.
3. Efficiency. Per-opportunity rates (catch rate, yards per target, TD per
   target, yards per carry, ...) shrunk toward the position's league rate
   with opportunity-count pseudo-observations: rates on few opportunities
   regress hard, TD rates hardest.
4. TD environment. TD rates scale with implied points relative to the
   league average implied total.

Output: per-stat means in this app's internal stat names (CORE values in
fantasy_decision_models), conditional on the player playing. League
scoring is applied by the caller exactly as for every other model.

Point-in-time: `project` only reads games that kicked off before `cutoff`
and lines observed at or before each game's cutoff. Retrospective runs use
stats as stored today, which can include later corrections; prospective
capture, not this backtest, is what qualifies a model (constraint: no
automatic promotion).

Initial hyperparameters (HALF_LIFE, SHARE_PRIOR_GAMES, RATE_PRIORS) are
documented starting values, not tuned on the weeks they are graded on.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game, PlayerGameStat, PlayerSnapCount
from src.models.identity import Player
from src.services.game_environment import environments

RECIPE = "projection_engine_v1"
POSITIONS = ("QB", "RB", "WR", "TE")
HALF_LIFE = 4.0  # games
SHARE_PRIOR_GAMES = 1.5
TEAM_LOOKBACK = 8  # team-games feeding the recent-volume feature
PLAYER_LOOKBACK = 12  # player-games feeding shares and rates

STATS = ("targets", "receptions", "receiving_yards", "receiving_touchdowns",
         "rushing_attempts", "rushing_yards", "rushing_touchdowns",
         "passing_attempts", "passing_completions", "passing_yards",
         "passing_touchdowns", "passing_interceptions", "fumbles_lost",
         "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions")

# (numerator stat, denominator stat, pseudo-opportunities). The prior is the
# position's pooled league rate; the pseudo-count sets how fast a player's
# own rate overrides it.
RATE_PRIORS = {
    "catch_rate": ("receptions", "targets", 40),
    "yards_per_target": ("receiving_yards", "targets", 40),
    "rec_td_rate": ("receiving_touchdowns", "targets", 120),
    "yards_per_carry": ("rushing_yards", "rushing_attempts", 60),
    "rush_td_rate": ("rushing_touchdowns", "rushing_attempts", 120),
    "completion_rate": ("passing_completions", "passing_attempts", 150),
    "yards_per_attempt": ("passing_yards", "passing_attempts", 150),
    "pass_td_rate": ("passing_touchdowns", "passing_attempts", 400),
    "int_rate": ("passing_interceptions", "passing_attempts", 400),
    "rec_2pt_rate": ("receiving_2pt_conversions", "targets", 400),
    "rush_2pt_rate": ("rushing_2pt_conversions", "rushing_attempts", 400),
    "pass_2pt_rate": ("passing_2pt_conversions", "passing_attempts", 800),
}


@dataclass
class TeamGame:
    game_id: uuid.UUID
    team_id: uuid.UUID
    kickoff: datetime
    pass_attempts: float = 0.0
    carries: float = 0.0
    targets: float = 0.0
    implied_points: float | None = None
    spread: float | None = None  # this team's handicap, negative when favoured


@dataclass
class PlayerGame:
    player_id: uuid.UUID
    game_id: uuid.UUID
    team_id: uuid.UUID
    kickoff: datetime
    stats: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Projection:
    player_id: uuid.UUID
    game_id: uuid.UUID
    team_id: uuid.UUID
    position: str
    stats: dict[str, float]
    games_used: int
    team_pass_attempts: float
    team_carries: float
    implied_points: float


def weights(n: int) -> np.ndarray:
    """Exponential recency weights, oldest first, newest weight 1."""
    return 0.5 ** (np.arange(n)[::-1] / HALF_LIFE)


def shrunk_share(values: list[float], prior: float) -> float:
    if not values:
        return prior
    w = weights(len(values))
    return float((np.dot(w, values) + SHARE_PRIOR_GAMES * prior) / (w.sum() + SHARE_PRIOR_GAMES))


def shrunk_rate(num: float, den: float, prior: float, pseudo: float) -> float:
    return (num + pseudo * prior) / (den + pseudo)


def fit_volume(rows: list[tuple[float, float, float, float]]) -> np.ndarray | None:
    """Least squares y ~ 1 + recent + implied + spread. rows: (recent, implied, spread, y)."""
    if len(rows) < 40:
        return None
    data = np.array(rows, dtype=float)
    design = np.column_stack([np.ones(len(data)), data[:, :3]])
    coef, *_ = np.linalg.lstsq(design, data[:, 3], rcond=None)
    return coef


def predict_volume(coef: np.ndarray | None, recent: float, implied: float, spread: float) -> float:
    if coef is None:
        return recent
    return max(0.0, float(coef @ np.array([1.0, recent, implied, spread])))


def team_features(history: list[TeamGame], stat: str) -> float | None:
    recent = history[-TEAM_LOOKBACK:]
    if not recent:
        return None
    w = weights(len(recent))
    return float(np.dot(w, [getattr(t, stat) for t in recent]) / w.sum())


def project_player(position: str, games: list[PlayerGame], teams: dict[tuple, TeamGame],
                   priors: dict[str, dict[str, float]], share_priors: dict[str, dict[str, float]],
                   team_pass: float, team_carries: float, td_scale: float,
                   targets_per_attempt: float) -> dict[str, float]:
    """Pure core for one player-game; `games` are his prior games, oldest first."""
    recent = games[-PLAYER_LOOKBACK:]

    def share(stat: str, team_stat: str) -> float:
        values = []
        for g in recent:
            team_total = getattr(teams[(g.game_id, g.team_id)], team_stat)
            if team_total > 0:
                values.append(g.stats.get(stat, 0.0) / team_total)
        return shrunk_share(values, share_priors[position][stat])

    def rate(name: str) -> float:
        num, den, pseudo = RATE_PRIORS[name]
        n = sum(g.stats.get(num, 0.0) for g in recent)
        d = sum(g.stats.get(den, 0.0) for g in recent)
        return shrunk_rate(n, d, priors[position][name], pseudo)

    # Target share is of team targets; team volume is projected in pass
    # attempts (sacks/throwaways/spikes make targets < attempts).
    targets = team_pass * targets_per_attempt * share("targets", "targets")
    carries = team_carries * share("rushing_attempts", "carries")
    attempts = team_pass * share("passing_attempts", "pass_attempts") if position == "QB" else 0.0
    touches = targets + carries
    fumble_rate = _fumbles_per_touch(recent)
    return {
        "targets": targets,
        "receptions": targets * rate("catch_rate"),
        "receiving_yards": targets * rate("yards_per_target"),
        "receiving_touchdowns": targets * rate("rec_td_rate") * td_scale,
        "receiving_2pt_conversions": targets * rate("rec_2pt_rate"),
        "rushing_attempts": carries,
        "rushing_yards": carries * rate("yards_per_carry"),
        "rushing_touchdowns": carries * rate("rush_td_rate") * td_scale,
        "rushing_2pt_conversions": carries * rate("rush_2pt_rate"),
        "passing_attempts": attempts,
        "passing_completions": attempts * rate("completion_rate"),
        "passing_yards": attempts * rate("yards_per_attempt"),
        "passing_touchdowns": attempts * rate("pass_td_rate") * td_scale,
        "passing_interceptions": attempts * rate("int_rate"),
        "passing_2pt_conversions": attempts * rate("pass_2pt_rate"),
        "fumbles_lost": (touches + attempts * 0.1) * fumble_rate,
    }


def _fumbles_per_touch(games: list[PlayerGame]) -> float:
    lost = sum(g.stats.get("fumbles_lost", 0.0) for g in games)
    touches = sum(g.stats.get("targets", 0.0) + g.stats.get("rushing_attempts", 0.0)
                  + 0.1 * g.stats.get("passing_attempts", 0.0) for g in games)
    return (lost + 0.5) / (touches + 250.0)  # ~0.2% per touch league-wide prior


async def load_history(db: AsyncSession, seasons: list[int], cutoff: datetime):
    """Team-games and player-games for completed games before cutoff."""
    games = {g.id: g for g in (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.season.in_(seasons), Game.status == "final",
        Game.game_time.is_not(None), Game.game_time < cutoff,
        or_(Game.game_type.is_(None), Game.game_type == "REG")))).all()}
    snaps = (await db.execute(select(PlayerSnapCount.player_id, PlayerSnapCount.game_id,
                                     PlayerSnapCount.team_id)
                              .where(PlayerSnapCount.game_id.in_(list(games))))).all()
    team_of = {(p, g): t for p, g, t in snaps}
    stat_rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id,
                                         PlayerGameStat.stat_type, PlayerGameStat.value)
                                  .where(PlayerGameStat.game_id.in_(list(games)),
                                         PlayerGameStat.stat_type.in_(STATS)))).all()
    players: dict[tuple, PlayerGame] = {}
    for player_id, game_id, stat, value in stat_rows:
        team_id = team_of.get((player_id, game_id))
        if team_id is None:
            continue  # no snap row: team unknown for this game, leave out
        key = (player_id, game_id)
        if key not in players:
            players[key] = PlayerGame(player_id, game_id, team_id, games[game_id].game_time)
        players[key].stats[stat] = value
    teams: dict[tuple, TeamGame] = {}
    for p in players.values():
        t = teams.setdefault((p.game_id, p.team_id), TeamGame(p.game_id, p.team_id, p.kickoff))
        t.pass_attempts += p.stats.get("passing_attempts", 0.0)
        t.carries += p.stats.get("rushing_attempts", 0.0)
        t.targets += p.stats.get("targets", 0.0)
    env = await environments(db, list(games), as_of={g.id: g.game_time for g in games.values()})
    for t in teams.values():
        e, g = env.get(t.game_id), games[t.game_id]
        if e is None:
            continue
        home = t.team_id == g.home_team_id
        t.implied_points = e.home_points if home else e.away_points
        t.spread = e.home_spread if home else -e.home_spread
    return games, teams, players


def league_priors(players: dict[tuple, PlayerGame], positions: dict[uuid.UUID, str],
                  teams: dict[tuple, TeamGame]):
    """Position-pooled efficiency rates and the share of a typical regular."""
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    share_lists: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for p in players.values():
        pos = positions.get(p.player_id)
        if pos not in POSITIONS:
            continue
        for stat in STATS:
            sums[pos][stat] += p.stats.get(stat, 0.0)
        team = teams[(p.game_id, p.team_id)]
        for stat, team_stat in (("targets", "targets"), ("rushing_attempts", "carries"),
                                ("passing_attempts", "pass_attempts")):
            total = getattr(team, team_stat)
            if total > 0:
                share_lists[pos][stat].append(p.stats.get(stat, 0.0) / total)
    priors = {pos: {name: (sums[pos][num] / sums[pos][den] if sums[pos][den] else 0.0)
                    for name, (num, den, _) in RATE_PRIORS.items()} for pos in POSITIONS}
    # Median share among players who recorded the stat: a fringe player's
    # handful of games pulls toward a modest role, not toward zero.
    share_priors = {pos: {stat: float(np.median([v for v in vals if v > 0])) if any(v > 0 for v in vals) else 0.0
                          for stat, vals in share_lists[pos].items()} for pos in POSITIONS}
    for pos in POSITIONS:
        for stat in ("targets", "rushing_attempts", "passing_attempts"):
            share_priors[pos].setdefault(stat, 0.0)
    return priors, share_priors


async def project(db: AsyncSession, target_games: list[Game], cutoff: datetime,
                  *, line_as_of: datetime | None = None) -> dict[uuid.UUID, Projection]:
    """Project every QB/RB/WR/TE whose latest team plays in one of target_games.

    `cutoff` bounds the history (games kicked off before it); `line_as_of`
    bounds the target games' lines (defaults to cutoff).
    """
    seasons = sorted({g.season for g in target_games} | {min(g.season for g in target_games) - 1})
    games, teams, players = await load_history(db, seasons, cutoff)
    position = dict((await db.execute(select(Player.id, Player.position).where(
        Player.id.in_({p.player_id for p in players.values()})))).all())
    priors, share_priors = league_priors(players, position, teams)

    by_team: dict[uuid.UUID, list[TeamGame]] = defaultdict(list)
    for t in sorted(teams.values(), key=lambda t: t.kickoff):
        by_team[t.team_id].append(t)
    pass_rows, carry_rows, implied_all = [], [], []
    for history in by_team.values():
        for i, t in enumerate(history):
            if t.implied_points is None or i < 3:
                continue
            implied_all.append(t.implied_points)
            pass_rows.append((team_features(history[:i], "pass_attempts"), t.implied_points, t.spread, t.pass_attempts))
            carry_rows.append((team_features(history[:i], "carries"), t.implied_points, t.spread, t.carries))
    pass_coef, carry_coef = fit_volume(pass_rows), fit_volume(carry_rows)
    league_implied = float(np.mean(implied_all)) if implied_all else 22.0
    league_attempts = sum(t.pass_attempts for t in teams.values())
    targets_per_attempt = sum(t.targets for t in teams.values()) / league_attempts if league_attempts else 1.0

    target_env = await environments(db, [g.id for g in target_games], as_of=line_as_of or cutoff)
    player_games: dict[uuid.UUID, list[PlayerGame]] = defaultdict(list)
    for p in sorted(players.values(), key=lambda p: p.kickoff):
        player_games[p.player_id].append(p)

    out: dict[uuid.UUID, Projection] = {}
    for game in target_games:
        env = target_env.get(game.id)
        if env is None:
            continue  # no line: no environment, no projection
        for team_id, implied, spread in ((game.home_team_id, env.home_points, env.home_spread),
                                         (game.away_team_id, env.away_points, -env.home_spread)):
            history = by_team.get(team_id, [])
            recent_pass, recent_carry = team_features(history, "pass_attempts"), team_features(history, "carries")
            if recent_pass is None or recent_carry is None:
                continue
            team_pass = predict_volume(pass_coef, recent_pass, implied, spread)
            team_carry = predict_volume(carry_coef, recent_carry, implied, spread)
            td_scale = implied / league_implied
            for player_id, pgs in player_games.items():
                pos = position.get(player_id)
                if pos not in POSITIONS or pgs[-1].team_id != team_id:
                    continue
                # Only the player's games for his current team define his role.
                own = [g for g in pgs if g.team_id == team_id]
                if len(own) < 1 or (cutoff - own[-1].kickoff).days > 400:
                    continue
                stats = project_player(pos, own, teams, priors, share_priors, team_pass, team_carry,
                                       td_scale, targets_per_attempt)
                if all(math.isfinite(v) for v in stats.values()):
                    out[player_id] = Projection(player_id, game.id, team_id, pos, stats, len(own[-PLAYER_LOOKBACK:]),
                                                team_pass, team_carry, implied)
    return out


def score(stats: dict[str, float], weights_by_stat: dict[str, float]) -> float:
    """League points from projected stats; weights keyed by internal stat name."""
    return sum(stats.get(stat, 0.0) * w for stat, w in weights_by_stat.items())
