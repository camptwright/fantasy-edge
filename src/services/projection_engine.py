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


@dataclass(frozen=True)
class Params:
    """Tunable hyperparameters; see scripts/tune_projection_engine.py.

    Defaults chosen 2026-10-12 by walk-forward on 2025 weeks 4-18 + 2026
    weeks 2-5 (owner-directed; 2026 is therefore in-sample): starter-pool
    MAE 5.739 -> 5.703. Chosen on 2025 alone, the best setting did not
    improve 2026 out of sample (5.858 vs 5.854), so the gain is marginal.
    """
    half_life: float = 2.0  # games
    share_prior_games: float = 1.5
    rate_scale: float = 2.0  # multiplies every RATE_PRIORS pseudo-count
    td_scale: float = 1.0  # extra multiplier on TD-rate pseudo-counts
    share_prior_quantile: float = 0.5  # quantile of positive shares used as share prior


DEFAULT = Params()
TD_RATES = ("rec_td_rate", "rush_td_rate", "pass_td_rate")


@dataclass
class History:
    games: dict
    teams: dict
    players: dict
    positions: dict


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


def weights(n: int, half_life: float = DEFAULT.half_life) -> np.ndarray:
    """Exponential recency weights, oldest first, newest weight 1."""
    return 0.5 ** (np.arange(n)[::-1] / half_life)


def shrunk_share(values: list[float], prior: float, params: Params = DEFAULT) -> float:
    if not values:
        return prior
    w = weights(len(values), params.half_life)
    k = params.share_prior_games
    return float((np.dot(w, values) + k * prior) / (w.sum() + k))


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


def team_features(history: list[TeamGame], stat: str, params: Params = DEFAULT) -> float | None:
    recent = history[-TEAM_LOOKBACK:]
    if not recent:
        return None
    w = weights(len(recent), params.half_life)
    return float(np.dot(w, [getattr(t, stat) for t in recent]) / w.sum())


SHARE_STATS = (("targets", "targets"), ("rushing_attempts", "carries"),
               ("passing_attempts", "pass_attempts"))


def player_shares(position: str, games: list[PlayerGame], teams: dict[tuple, TeamGame],
                  share_priors: dict[str, dict[str, float]], params: Params = DEFAULT) -> dict[str, float]:
    """Shrunk share of each team volume stat; only QBs are given pass attempts."""
    recent = games[-PLAYER_LOOKBACK:]
    out = {}
    for stat, team_stat in SHARE_STATS:
        if stat == "passing_attempts" and position != "QB":
            out[stat] = 0.0
            continue
        values = []
        for g in recent:
            team_total = getattr(teams[(g.game_id, g.team_id)], team_stat)
            if team_total > 0:
                values.append(g.stats.get(stat, 0.0) / team_total)
        out[stat] = shrunk_share(values, share_priors[position][stat], params)
    return out


def project_player(position: str, games: list[PlayerGame], priors: dict[str, dict[str, float]],
                   shares: dict[str, float], team_pass: float, team_carries: float, td_scale: float,
                   targets_per_attempt: float, params: Params = DEFAULT) -> dict[str, float]:
    """Pure core for one player-game; `games` are his prior games, oldest first."""
    recent = games[-PLAYER_LOOKBACK:]

    def rate(name: str) -> float:
        num, den, pseudo = RATE_PRIORS[name]
        pseudo *= params.rate_scale * (params.td_scale if name in TD_RATES else 1.0)
        n = sum(g.stats.get(num, 0.0) for g in recent)
        d = sum(g.stats.get(den, 0.0) for g in recent)
        return shrunk_rate(n, d, priors[position][name], pseudo)

    # Target share is of team targets; team volume is projected in pass
    # attempts (sacks/throwaways/spikes make targets < attempts).
    targets = team_pass * targets_per_attempt * shares["targets"]
    carries = team_carries * shares["rushing_attempts"]
    attempts = team_pass * shares["passing_attempts"]
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


async def load_history(db: AsyncSession, seasons: list[int], cutoff: datetime) -> History:
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
    positions = dict((await db.execute(select(Player.id, Player.position).where(
        Player.id.in_({p.player_id for p in players.values()})))).all())
    return History(games, teams, players, positions)


def league_priors(players: dict[tuple, PlayerGame], positions: dict[uuid.UUID, str],
                  teams: dict[tuple, TeamGame], params: Params = DEFAULT):
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
    # A quantile of the shares of players who recorded the stat: a fringe
    # player's handful of games pulls toward a modest role, not toward zero.
    q = params.share_prior_quantile
    share_priors = {pos: {stat: float(np.quantile([v for v in vals if v > 0], q)) if any(v > 0 for v in vals) else 0.0
                          for stat, vals in share_lists[pos].items()} for pos in POSITIONS}
    for pos in POSITIONS:
        for stat in ("targets", "rushing_attempts", "passing_attempts"):
            share_priors[pos].setdefault(stat, 0.0)
    return priors, share_priors


async def project(db: AsyncSession, target_games: list[Game], cutoff: datetime,
                  *, line_as_of: datetime | None = None,
                  params: Params = DEFAULT) -> dict[uuid.UUID, Projection]:
    """Project every QB/RB/WR/TE whose latest team plays in one of target_games.

    `cutoff` bounds the history (games kicked off before it); `line_as_of`
    bounds the target games' lines (defaults to cutoff).
    """
    seasons = sorted({g.season for g in target_games} | {min(g.season for g in target_games) - 1})
    history = await load_history(db, seasons, cutoff)
    env = await environments(db, [g.id for g in target_games], as_of=line_as_of or cutoff)
    targets = [(g, env[g.id].home_points, env[g.id].away_points, env[g.id].home_spread)
               for g in target_games if g.id in env]  # no line: no environment, no projection
    return compute(history, targets, cutoff, params)


def compute(history: History, targets: list[tuple], cutoff: datetime,
            params: Params = DEFAULT) -> dict[uuid.UUID, Projection]:
    """Pure core. targets: (game, home_points, away_points, home_spread).

    Only history that kicked off before `cutoff` is used, so one loaded
    History can serve a whole walk-forward.
    """
    players = {k: p for k, p in history.players.items() if p.kickoff < cutoff}
    teams = {k: t for k, t in history.teams.items() if t.kickoff < cutoff}
    position = history.positions
    priors, share_priors = league_priors(players, position, teams, params)

    by_team: dict[uuid.UUID, list[TeamGame]] = defaultdict(list)
    for t in sorted(teams.values(), key=lambda t: t.kickoff):
        by_team[t.team_id].append(t)
    pass_rows, carry_rows, implied_all = [], [], []
    for team_history in by_team.values():
        for i, t in enumerate(team_history):
            if t.implied_points is None or i < 3:
                continue
            implied_all.append(t.implied_points)
            pass_rows.append((team_features(team_history[:i], "pass_attempts", params),
                              t.implied_points, t.spread, t.pass_attempts))
            carry_rows.append((team_features(team_history[:i], "carries", params),
                               t.implied_points, t.spread, t.carries))
    pass_coef, carry_coef = fit_volume(pass_rows), fit_volume(carry_rows)
    league_implied = float(np.mean(implied_all)) if implied_all else 22.0
    league_attempts = sum(t.pass_attempts for t in teams.values())
    targets_per_attempt = sum(t.targets for t in teams.values()) / league_attempts if league_attempts else 1.0

    player_games: dict[uuid.UUID, list[PlayerGame]] = defaultdict(list)
    for p in sorted(players.values(), key=lambda p: p.kickoff):
        player_games[p.player_id].append(p)

    out: dict[uuid.UUID, Projection] = {}
    for game, home_points, away_points, home_spread in targets:
        for team_id, implied, spread in ((game.home_team_id, home_points, home_spread),
                                         (game.away_team_id, away_points, -home_spread)):
            team_history = by_team.get(team_id, [])
            recent_pass = team_features(team_history, "pass_attempts", params)
            recent_carry = team_features(team_history, "carries", params)
            if recent_pass is None or recent_carry is None:
                continue
            team_pass = predict_volume(pass_coef, recent_pass, implied, spread)
            team_carry = predict_volume(carry_coef, recent_carry, implied, spread)
            td_scale = implied / league_implied
            roster = {}
            for player_id, pgs in player_games.items():
                pos = position.get(player_id)
                if pos not in POSITIONS or pgs[-1].team_id != team_id:
                    continue
                # Only the player's games for his current team define his role.
                own = [g for g in pgs if g.team_id == team_id]
                if (cutoff - own[-1].kickoff).days > 400:
                    continue
                roster[player_id] = (pos, own)
            for player_id, (pos, own) in roster.items():
                # Shares are not capped per team: without knowing who is
                # active (E3), every player last seen on the team would count
                # toward the cap and starters would be scaled down (tried
                # 2026-10-12: walk-forward pool MAE 5.74 -> 6.50).
                shares = player_shares(pos, own, teams, share_priors, params)
                stats = project_player(pos, own, priors, shares, team_pass, team_carry,
                                       td_scale, targets_per_attempt, params)
                if all(math.isfinite(v) for v in stats.values()):
                    out[player_id] = Projection(player_id, game.id, team_id, pos, stats,
                                                len(own[-PLAYER_LOOKBACK:]), team_pass, team_carry, implied)
    return out


def score(stats: dict[str, float], weights_by_stat: dict[str, float]) -> float:
    """League points from projected stats; weights keyed by internal stat name."""
    return sum(stats.get(stat, 0.0) * w for stat, w in weights_by_stat.items())
