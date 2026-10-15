"""Projection engine v2: learned team volume -> player share -> per-stat rates.

Plan and evidence: docs/2026-10-15-engine-v2-plan.md. v1
(projection_engine.py) is left untouched so its prospective record keeps
accruing; v2 is a separate recipe.

Same chain as v1, but each stage is a ridge regression refit at every cutoff
on games that kicked off before it, instead of hand-set shrinkage:

1. Team volume. Pass attempts and carries from the team's trailing volume and
   the game's implied points and spread (core), plus play-selection and pace
   (team_play) and the opponent's volume allowed (opponent).
2. Player share. Target, carry and pass-attempt shares from v1's shrunk
   recency share (core) plus feature groups: offseason prior (last season's
   share, Sleeper's week-1 projection, rookie draft capital, vacated
   volume, team change), role speed (several half-lives, last game, snap
   share and its trend), opportunity quality (red-zone and goal-line
   shares), QB rushing detail.
3. Per-stat rates. Each stat is a ridge stack of opportunity x rate
   products: the player's shrunk historical rate and the league rate (core),
   expected rates from nflverse ff_opportunity (opportunity), depth of
   target (depth), over-expectation efficiency (efficiency) and the
   opponent's rate allowed (opponent).

Every feature belongs to one group (FEATURE_GROUP) so each workstream can be
switched on alone and graded. Pure numpy: the serving image has no sklearn.
Records are plain dicts so the research loader (nflverse) and a database
loader can feed the same code.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

RECIPE = "projection_engine_v2"
POSITIONS = ("QB", "RB", "WR", "TE")
GROUPS = ("core", "offseason", "role", "availability", "opportunity", "team_play", "qb_rush", "depth", "efficiency",
          "opponent", "sleeper_prev")
VOLUME_DENOM = {"targets": 33.0, "rushing_attempts": 27.0, "passing_attempts": 34.0}  # league team volume per game
PLAYER_GAMES = 12
TEAM_GAMES = 8
HALF_LIFE = 2.0  # v1's default, games
SHARE_PRIOR_GAMES = 1.5  # v1's default
RIDGE = 10.0

STATS = ("targets", "receptions", "receiving_yards", "receiving_touchdowns",
         "rushing_attempts", "rushing_yards", "rushing_touchdowns",
         "passing_attempts", "passing_completions", "passing_yards",
         "passing_touchdowns", "passing_interceptions", "fumbles_lost",
         "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions")
SHARES = {"targets": "targets", "rushing_attempts": "carries", "passing_attempts": "pass_att"}

# rate name -> (numerator, denominator, pseudo-opportunities), v1's values x2 (its rate_scale)
RATES = {
    "catch_rate": ("receptions", "targets", 80),
    "yards_per_target": ("receiving_yards", "targets", 80),
    "rec_td_rate": ("receiving_touchdowns", "targets", 240),
    "yards_per_carry": ("rushing_yards", "rushing_attempts", 120),
    "rush_td_rate": ("rushing_touchdowns", "rushing_attempts", 240),
    "completion_rate": ("passing_completions", "passing_attempts", 300),
    "yards_per_attempt": ("passing_yards", "passing_attempts", 300),
    "pass_td_rate": ("passing_touchdowns", "passing_attempts", 800),
    "int_rate": ("passing_interceptions", "passing_attempts", 800),
}
# expected-value rates from ff_opportunity: (expected numerator, denominator, pseudo)
X_RATES = {
    "x_catch_rate": ("x_receptions", "targets", 20),
    "x_yards_per_target": ("x_receiving_yards", "targets", 20),
    "x_rec_td_rate": ("x_receiving_touchdowns", "targets", 40),
    "x_yards_per_carry": ("x_rushing_yards", "rushing_attempts", 30),
    "x_rush_td_rate": ("x_rushing_touchdowns", "rushing_attempts", 40),
    "x_completion_rate": ("x_passing_completions", "passing_attempts", 75),
    "x_yards_per_attempt": ("x_passing_yards", "passing_attempts", 75),
    "x_pass_td_rate": ("x_passing_touchdowns", "passing_attempts", 150),
    "x_int_rate": ("x_passing_interceptions", "passing_attempts", 150),
}
MINOR = {"fumbles_lost": 0.002, "passing_2pt_conversions": 0.0015,
         "rushing_2pt_conversions": 0.002, "receiving_2pt_conversions": 0.0012}  # per opportunity


def ewma(values: list, half_life: float = HALF_LIFE) -> float:
    pairs = [(i, v) for i, v in enumerate(values) if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not pairs:
        return math.nan
    n = len(values)
    w = np.array([0.5 ** ((n - 1 - i) / half_life) for i, _ in pairs])
    return float(np.dot(w, [v for _, v in pairs]) / w.sum())


def shrunk_share(values: list[float], prior: float) -> float:
    """v1's share: recency-weighted, shrunk toward a prior by SHARE_PRIOR_GAMES."""
    if not values:
        return prior
    w = 0.5 ** (np.arange(len(values))[::-1] / HALF_LIFE)
    return float((np.dot(w, values) + SHARE_PRIOR_GAMES * prior) / (w.sum() + SHARE_PRIOR_GAMES))


def shrunk(num: float, den: float, prior: float, pseudo: float) -> float:
    return (num + pseudo * prior) / (den + pseudo)


# ---------------------------------------------------------------- features

def league_rates(games: list[dict], positions=POSITIONS) -> dict:
    """Position-pooled rates and v1's share priors (median of positive shares)."""
    sums = defaultdict(lambda: defaultdict(float))
    shares = defaultdict(lambda: defaultdict(list))
    for g in games:
        pos = g["position"]
        if pos not in positions:
            continue
        for stat, v in g["stats"].items():
            sums[pos][stat] += v
        for k in ("x_receptions", "x_receiving_yards", "x_receiving_touchdowns", "x_rushing_yards",
                  "x_rushing_touchdowns", "x_passing_completions", "x_passing_yards",
                  "x_passing_touchdowns", "x_passing_interceptions"):
            if g.get(k) is not None:
                sums[pos][k] += g[k]
                sums[pos]["den_" + k] += g["stats"][X_DEN[k]]
        for stat, team_key in SHARES.items():
            if g["team_" + team_key] > 0 and g["stats"][stat] > 0:
                shares[pos][stat].append(g["stats"][stat] / g["team_" + team_key])
    out = {}
    for pos in positions:
        s = sums[pos]
        r = {name: (s[num] / s[den] if s[den] else 0.0) for name, (num, den, _) in RATES.items()}
        for name, (num, den, _) in X_RATES.items():
            r[name] = s[num] / s["den_" + num] if s["den_" + num] else r[name[2:]]
        r["share_prior"] = {stat: float(np.median(v)) if v else 0.0 for stat, v in
                            ((stat, shares[pos][stat]) for stat in SHARES)}
        out[pos] = r
    return out


X_DEN = {"x_receptions": "targets", "x_receiving_yards": "targets", "x_receiving_touchdowns": "targets",
         "x_rushing_yards": "rushing_attempts", "x_rushing_touchdowns": "rushing_attempts",
         "x_passing_completions": "passing_attempts", "x_passing_yards": "passing_attempts",
         "x_passing_touchdowns": "passing_attempts", "x_passing_interceptions": "passing_attempts"}


FEATURE_GROUP: dict[str, str] = {}


def _tag(group: str, *names: str):
    for n in names:
        FEATURE_GROUP[n] = group


_tag("core", "t_pass", "t_car", "t_tpa", "implied", "spread", "v1_share_targets", "v1_share_rushing_attempts",
     "v1_share_passing_attempts")
_tag("team_play", "t_proe", "t_plays", "t_dropbacks", "total", "t_pass_rate")
_tag("opponent", "o_pass_allowed", "o_car_allowed", "o_plays_allowed")
_tag("offseason", "games_season", "decay", "prev_share_targets", "prev_share_rushing_attempts",
     "prev_share_passing_attempts", "prev_share_targets_d", "prev_share_rushing_attempts_d",
     "prev_share_passing_attempts_d", "sl_w1_targets", "sl_w1_rushing_attempts", "sl_w1_passing_attempts",
     "sl_w1_targets_d", "sl_w1_rushing_attempts_d", "sl_w1_passing_attempts_d", "sl_w1_missing",
     "rookie", "rookie_pick_d", "team_changed_d", "vacated_targets", "vacated_rushing_attempts",
     "vacated_targets_d", "vacated_rushing_attempts_d", "no_history")
_tag("role", "share_fast_targets", "share_fast_rushing_attempts", "share_fast_passing_attempts",
     "share_slow_targets", "share_slow_rushing_attempts", "share_slow_passing_attempts",
     "share_last_targets", "share_last_rushing_attempts", "share_last_passing_attempts",
     "snap", "snap_last", "snap_delta", "days_rest_long")
_tag("availability", "out_targets", "out_rushing_attempts", "out_passing_attempts", "out_pos_targets",
     "out_pos_rushing_attempts", "out_pos_passing_attempts", "return_targets", "return_rushing_attempts",
     "return_pos_targets", "return_pos_rushing_attempts", "return_pos_passing_attempts", "depth_rank", "depth_missing",
     "depth_starter")
# Sleeper's projected volume for the player's previous game. Never the game being projected:
# Sleeper's archive revises a week's projections with in-game news.
_tag("sleeper_prev", "sl_prev_targets", "sl_prev_rushing_attempts", "sl_prev_passing_attempts", "sl_prev_missing")
_tag("opportunity", "rz_tgt_share", "ez_tgt_share", "rz_car_share", "gl_car_share")
_tag("qb_rush", "designed_share", "scramble_rate")
_tag("depth", "adot", "air_share")


def team_features(prior: list[dict], target: dict, opp_def_prior: list[dict]) -> dict:
    """Trailing team features for one team-game (prior = this team's earlier games, oldest first)."""
    recent = prior[-TEAM_GAMES:]
    f = {"implied": target["implied"], "spread": target["spread"], "total": target["total"]}
    if not recent:
        return f
    col = {k: [g[k] for g in recent] for k in ("pass_att", "carries", "targets", "plays", "dropbacks", "proe")}
    f["t_pass"], f["t_car"] = ewma(col["pass_att"]), ewma(col["carries"])
    f["t_tpa"] = sum(col["targets"]) / sum(col["pass_att"]) if sum(col["pass_att"]) else math.nan
    f["t_plays"], f["t_dropbacks"], f["t_proe"] = ewma(col["plays"]), ewma(col["dropbacks"]), ewma(col["proe"])
    f["t_pass_rate"] = f["t_dropbacks"] / f["t_plays"] if f["t_plays"] else math.nan
    allowed = opp_def_prior[-TEAM_GAMES:]
    if allowed:
        f["o_pass_allowed"] = ewma([g["pass_att"] for g in allowed])
        f["o_car_allowed"] = ewma([g["carries"] for g in allowed])
        f["o_plays_allowed"] = ewma([g["plays"] for g in allowed])
    return f


def _share(g: dict, stat: str) -> float | None:
    total = g["team_" + SHARES[stat]]
    return g["stats"][stat] / total if total > 0 else None


def player_features(prior: list[dict], target: dict, ctx: dict, rates: dict) -> dict:
    """Trailing player features for one player-game.

    prior: this player's earlier games, oldest first, any team. target: the
    game being projected (season, week, team, kickoff, position). ctx:
    pre-game context (sleeper_w1 projection, rookie draft pick, vacated
    volume). rates: league_rates for seasons before the target's.
    """
    pos = target["position"]
    lr = rates[pos]
    own = [g for g in prior if g["team"] == target["team"]][-PLAYER_GAMES:]
    recent = prior[-PLAYER_GAMES:]
    this_season = [g for g in prior if g["season"] == target["season"]]
    last_season = [g for g in prior if g["season"] == target["season"] - 1]
    games_season = len(this_season)
    decay = 1.0 / (1.0 + games_season)
    f = {"games_season": games_season, "decay": decay, "no_history": float(not prior)}
    for stat in SHARES:
        vals = [s for s in (_share(g, stat) for g in own) if s is not None]
        f[f"v1_share_{stat}"] = shrunk_share(vals, lr["share_prior"][stat]) if (stat != "passing_attempts" or pos == "QB") else 0.0
        allv = [_share(g, stat) for g in recent]
        f[f"share_fast_{stat}"] = ewma(allv, 1.0)
        f[f"share_slow_{stat}"] = ewma(allv, 6.0)
        f[f"share_last_{stat}"] = allv[-1] if allv and allv[-1] is not None else math.nan
        prev = [s for s in (_share(g, stat) for g in last_season) if s is not None]
        f[f"prev_share_{stat}"] = float(np.mean(prev)) if prev else math.nan
        f[f"prev_share_{stat}_d"] = f[f"prev_share_{stat}"] * decay if prev else math.nan
        sl = (ctx.get("sleeper_w1") or {}).get(stat)
        if sl is not None:
            f[f"sl_w1_{stat}"] = sl / VOLUME_DENOM[stat]
            f[f"sl_w1_{stat}_d"] = sl / VOLUME_DENOM[stat] * decay
    f["sl_w1_missing"] = float(ctx.get("sleeper_w1") is None)
    pick = ctx.get("rookie_pick")
    f["rookie"] = float(pick is not None)
    f["rookie_pick_d"] = (1.0 - math.log(pick) / math.log(260)) * decay if pick else 0.0
    last_team = prior[-1]["team"] if prior else None
    f["team_changed_d"] = float(last_team is not None and last_team != target["team"]) * decay
    for stat in ("targets", "rushing_attempts"):
        v = (ctx.get("vacated") or {}).get(stat)
        if v is not None:
            f[f"vacated_{stat}"] = v
            f[f"vacated_{stat}_d"] = v * decay
    avail = ctx.get("availability") or {}
    team_av, pos_av = avail.get("*", {}), avail.get(pos, {})
    for kind in ("out", "return"):
        for stat in SHARES:
            f[f"{kind}_{stat}"] = team_av.get(f"{kind}_{stat}", 0.0)
            f[f"{kind}_pos_{stat}"] = pos_av.get(f"{kind}_{stat}", 0.0)
    rank = ctx.get("depth_rank")
    f["depth_missing"] = float(rank is None)
    f["depth_rank"] = float(min(rank, 4)) if rank is not None else math.nan
    f["depth_starter"] = float(rank == 1)
    snaps = [g.get("snap_pct") for g in recent]
    f["snap"] = ewma(snaps)
    f["snap_last"] = snaps[-1] if snaps and snaps[-1] is not None else math.nan
    f["snap_delta"] = f["snap_last"] - f["snap"] if not (math.isnan(f["snap_last"]) or math.isnan(f["snap"])) else math.nan
    f["days_rest_long"] = float(bool(prior) and (target["kickoff"] - prior[-1]["kickoff"]).days > 20)

    def team_share(key, team_key):
        num = [g.get(key, 0.0) for g in recent]
        den = [g.get("team_" + team_key, 0.0) for g in recent]
        return ewma([n / d if d else None for n, d in zip(num, den)], 3.0)
    f["rz_tgt_share"] = team_share("rz_tgt", "rz_targets")
    f["ez_tgt_share"] = team_share("ez_tgt", "targets")
    f["rz_car_share"] = team_share("rz_car", "rz_carries")
    f["gl_car_share"] = team_share("gl_car", "gl_carries")
    f["designed_share"] = team_share("designed_runs", "carries")
    f["scramble_rate"] = team_share("scrambles", "dropbacks")
    tg = sum(g["stats"]["targets"] for g in recent)
    f["adot"] = sum(g.get("air_yards", 0.0) for g in recent) / tg if tg >= 5 else math.nan
    f["air_share"] = team_share("air_yards", "air_yards")

    # rates over the last 2 x PLAYER_GAMES games (TD rates need the sample)
    long = prior[-2 * PLAYER_GAMES:]
    for name, (num, den, pseudo) in RATES.items():
        n = sum(g["stats"][num] for g in long)
        d = sum(g["stats"][den] for g in long)
        f["r_" + name] = shrunk(n, d, lr[name], pseudo)
    for name, (num, den, pseudo) in X_RATES.items():
        pairs = [(g[num], g["stats"][den]) for g in long if g.get(num) is not None]
        f["r_" + name] = shrunk(sum(p[0] for p in pairs), sum(p[1] for p in pairs), lr[name], pseudo)
    # over-expectation efficiency: actual rate minus expected rate on the same plays, shrunk to 0
    for label, (actual, expected, den, pseudo) in {
            "e_ryoe": ("rushing_yards", "x_rushing_yards", "rushing_attempts", 150),
            "e_yacoe": ("receiving_yards", "x_receiving_yards", "targets", 100),
            "e_cpoe": ("passing_completions", "x_passing_completions", "passing_attempts", 300)}.items():
        pairs = [(g["stats"][actual], g[expected], g["stats"][den]) for g in long if g.get(expected) is not None]
        d = sum(p[2] for p in pairs)
        f[label] = (sum(p[0] - p[1] for p in pairs)) / (d + pseudo)
    fum_touch = sum(g["stats"]["targets"] + g["stats"]["rushing_attempts"] + 0.1 * g["stats"]["passing_attempts"]
                    for g in long)
    f["r_fumble"] = (sum(g["stats"]["fumbles_lost"] for g in long) + 0.5) / (fum_touch + 250.0)
    return f




# ---------------------------------------------------------------- frames and ridge

@dataclass
class Frame:
    """Feature rows as one float matrix (NaN = missing) plus per-row metadata.

    actual: per-stat actuals (NaN where unknown, e.g. a game not yet played);
    team: actual team targets/carries/pass attempts in that game.
    """
    names: list[str]
    X: np.ndarray
    position: np.ndarray
    actual: np.ndarray
    team: np.ndarray

    @classmethod
    def from_rows(cls, rows: list[dict], names: list[str] | None = None) -> "Frame":
        names = names or sorted({k for r in rows for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                                 and k not in ("season", "week")} | set(FEATURE_GROUP))
        X = np.array([[_num(r.get(n)) for n in names] for r in rows], float).reshape(len(rows), len(names))
        actual = np.array([[_num((r.get("stats") or {}).get(s)) for s in STATS] for r in rows], float).reshape(len(rows), len(STATS))
        team = np.array([[_num(r.get("team_" + SHARES[s])) for s in SHARES] for r in rows], float).reshape(len(rows), len(SHARES))
        return cls(names, X, np.array([r.get("position") for r in rows], dtype=object), actual, team)

    def col(self, name: str) -> np.ndarray:
        try:
            return self.X[:, self.names.index(name)]
        except ValueError:
            return np.full(len(self.X), math.nan)

    def cols(self, names: list[str]) -> np.ndarray:
        return np.column_stack([self.col(n) for n in names]) if names else np.zeros((len(self.X), 0))

    def stat(self, stat: str) -> np.ndarray:
        return self.actual[:, STATS.index(stat)]

    def team_total(self, stat: str) -> np.ndarray:
        return self.team[:, list(SHARES).index(stat)]


def row_names() -> list[str]:
    """Every column a model stage can read, for building a Frame without keeping row dicts."""
    names = set(FEATURE_GROUP) | set(TEAM_FEATURES) | {"t_tpa", "r_fumble", "e_ryoe", "e_yacoe", "e_cpoe"}
    names |= {"r_" + n for n in RATES} | {"r_" + n for n in X_RATES} | {"lg_" + n for n in RATES}
    for _, parts, _ in STACKS.values():
        names |= {n[:-5] if n.endswith("@team") else n for n, _ in parts}
    return sorted(names)


def frame_from_iter(rows, names: list[str]) -> Frame:
    """Frame.from_rows for a one-pass iterable of row dicts (constant memory per row)."""
    X, actual, team, position = [], [], [], []
    for r in rows:
        X.append(np.array([_num(r.get(n)) for n in names], float))
        st = r.get("stats") or {}
        actual.append(np.array([_num(st.get(s)) for s in STATS], float))
        team.append(np.array([_num(r.get("team_" + SHARES[s])) for s in SHARES], float))
        position.append(r.get("position"))
    n = len(X)
    return Frame(names, np.vstack(X) if n else np.zeros((0, len(names))), np.array(position, dtype=object),
                 np.vstack(actual) if n else np.zeros((0, len(STATS))), np.vstack(team) if n else np.zeros((0, len(SHARES))))


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else math.nan


@dataclass
class Ridge:
    names: list[str]
    fill: np.ndarray
    flags: list[int]
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    lo: float | None = None
    hi: float | None = None

    def design(self, raw: np.ndarray) -> np.ndarray:
        miss = np.isnan(raw)
        X = np.where(miss, self.fill, raw)
        return np.hstack([X, miss[:, self.flags].astype(float)]) if self.flags else X

    def predict(self, frame: Frame, mask=None) -> np.ndarray:
        raw = frame.cols(self.names) if mask is None else frame.cols(self.names)[mask]
        y = ((self.design(raw) - self.mean) / self.scale) @ self.coef + self.intercept
        return y if self.lo is None and self.hi is None else np.clip(y, self.lo, self.hi)


def fit_ridge(frame: Frame, mask: np.ndarray, y: np.ndarray, names: list[str], alpha: float = RIDGE,
              lo: float | None = None, hi: float | None = None) -> Ridge:
    raw = frame.cols(names)[mask]
    miss = np.isnan(raw)
    with np.errstate(all="ignore"):
        fill = np.where(miss.all(0), 0.0, np.nanmedian(np.where(miss.all(0), 0.0, raw), axis=0))
    flags = [j for j in range(raw.shape[1]) if miss[:, j].any() and not miss[:, j].all()]
    m = Ridge(names, fill, flags, None, None, None, 0.0, lo, hi)
    X = m.design(raw)
    m.mean, m.scale = X.mean(0), X.std(0)
    m.scale[m.scale == 0] = 1.0
    Z = (X - m.mean) / m.scale
    m.intercept = float(y.mean()) if len(y) else 0.0
    m.coef = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - m.intercept)) if Z.shape[1] else np.zeros(0)
    return m


# ---------------------------------------------------------------- model

TEAM_FEATURES = ("t_pass", "t_car", "implied", "spread", "t_proe", "t_plays", "t_dropbacks", "total",
                 "t_pass_rate", "o_pass_allowed", "o_car_allowed", "o_plays_allowed")
_STAT_SUFFIX = tuple(f"_{s}{d}" for s in SHARES for d in ("", "_d"))


def share_features(stat: str, position: str, groups: frozenset) -> list[str]:
    out = []
    for n, g in FEATURE_GROUP.items():
        if g not in groups or g in ("team_play", "opponent"):
            continue
        if n in ("t_pass", "t_car", "t_tpa"):
            continue
        if n.endswith(_STAT_SUFFIX) and not n.endswith((f"_{stat}", f"_{stat}_d")):
            continue
        if g == "qb_rush" and (position != "QB" or stat != "rushing_attempts"):
            continue
        out.append(n)
    return out


# stat -> (opportunity, [(rate column, group)], TD-like: scales with implied points)
STACKS = {
    "receptions": ("targets", [("r_catch_rate", "core"), ("lg_catch_rate", "core"),
                               ("r_x_catch_rate", "opportunity"), ("adot", "depth")], False),
    "receiving_yards": ("targets", [("r_yards_per_target", "core"), ("lg_yards_per_target", "core"),
                                    ("r_x_yards_per_target", "opportunity"), ("adot", "depth"),
                                    ("e_yacoe", "efficiency")], False),
    "receiving_touchdowns": ("targets", [("r_rec_td_rate", "core"), ("lg_rec_td_rate", "core"),
                                         ("r_x_rec_td_rate", "opportunity"), ("rz_tgt_share@team", "opportunity"),
                                         ("ez_tgt_share@team", "opportunity")], True),
    "rushing_yards": ("rushing_attempts", [("r_yards_per_carry", "core"), ("lg_yards_per_carry", "core"),
                                           ("r_x_yards_per_carry", "opportunity"), ("e_ryoe", "efficiency")], False),
    "rushing_touchdowns": ("rushing_attempts", [("r_rush_td_rate", "core"), ("lg_rush_td_rate", "core"),
                                                ("r_x_rush_td_rate", "opportunity"), ("gl_car_share@team", "opportunity"),
                                                ("rz_car_share@team", "opportunity")], True),
    "passing_completions": ("passing_attempts", [("r_completion_rate", "core"), ("lg_completion_rate", "core"),
                                                 ("r_x_completion_rate", "opportunity"), ("e_cpoe", "efficiency")], False),
    "passing_yards": ("passing_attempts", [("r_yards_per_attempt", "core"), ("lg_yards_per_attempt", "core"),
                                           ("r_x_yards_per_attempt", "opportunity")], False),
    "passing_touchdowns": ("passing_attempts", [("r_pass_td_rate", "core"), ("lg_pass_td_rate", "core"),
                                                ("r_x_pass_td_rate", "opportunity")], True),
    "passing_interceptions": ("passing_attempts", [("r_int_rate", "core"), ("lg_int_rate", "core"),
                                                   ("r_x_int_rate", "opportunity")], False),
}
STACK_POSITIONS = {"receptions": POSITIONS, "receiving_yards": POSITIONS,
                   "receiving_touchdowns": ("RB", "WR", "TE"), "rushing_yards": POSITIONS,
                   "rushing_touchdowns": POSITIONS, "passing_completions": ("QB",), "passing_yards": ("QB",),
                   "passing_touchdowns": ("QB",), "passing_interceptions": ("QB",)}
# a red-zone/goal-line share times the team's projected volume of that kind
_TEAM_OPP = {"rz_tgt_share": "targets", "ez_tgt_share": "targets", "gl_car_share": "rushing_attempts",
             "rz_car_share": "rushing_attempts"}


@dataclass
class Model:
    groups: frozenset
    team: dict = field(default_factory=dict)
    share: dict = field(default_factory=dict)
    stack: dict = field(default_factory=dict)
    league_implied: float = 22.0


def _team_volume(model: Model, frame: Frame, mask) -> dict[str, np.ndarray]:
    tp = model.team["pass_att"].predict(frame, mask)
    tc = model.team["carries"].predict(frame, mask)
    tpa = frame.col("t_tpa")[mask]
    tpa = np.where(np.isnan(tpa), 0.9, tpa)
    return {"targets": tp * tpa, "rushing_attempts": tc, "passing_attempts": tp}


def _products(frame: Frame, mask, stat: str, groups: frozenset, opp: np.ndarray,
              team: dict, imp_scale: np.ndarray) -> tuple[list[str], np.ndarray]:
    opportunity, parts, td = STACKS[stat]
    scale = imp_scale if td else 1.0
    names, cols = [], []
    for name, group in parts:
        if group not in groups:
            continue
        if name.endswith("@team"):
            base = name[:-5]
            v = np.nan_to_num(frame.col(base)[mask])
            cols.append(v * team[_TEAM_OPP[base]] * 0.1 * scale)
        else:
            cols.append(np.nan_to_num(frame.col(name)[mask]) * opp * scale)
        names.append(name)
    return names, (np.column_stack(cols) if cols else np.zeros((int(np.sum(mask)), 0)))


def _imp_scale(model: Model, frame: Frame, mask) -> np.ndarray:
    imp = frame.col("implied")[mask]
    return np.where(np.isnan(imp), 1.0, imp / model.league_implied)


def fit(team_frame: Frame, team_y: dict[str, np.ndarray], team_mask: np.ndarray,
        frame: Frame, mask: np.ndarray, groups=("core",)) -> Model:
    """Fit every stage on rows that already happened (mask: rows to learn from)."""
    groups = frozenset(groups) | {"core"}
    model = Model(groups)
    names = [n for n in TEAM_FEATURES if FEATURE_GROUP.get(n, "core") in groups]
    usable = team_mask & ~np.isnan(team_frame.col("t_pass"))
    for stat in ("pass_att", "carries"):
        model.team[stat] = fit_ridge(team_frame, usable, team_y[stat][usable], names, lo=0.0)
    imp = team_frame.col("implied")[usable]
    model.league_implied = float(np.nanmean(imp)) if np.isfinite(imp).any() else 22.0
    for pos in POSITIONS:
        sel = mask & (frame.position == pos)
        if not sel.any():
            continue
        team = _team_volume(model, frame, sel)
        opp = {}
        for stat in SHARES:
            if stat == "passing_attempts" and pos != "QB":
                opp[stat] = np.zeros(int(sel.sum()))
                continue
            total = frame.team_total(stat)[sel]
            y = np.where(total > 0, frame.stat(stat)[sel] / np.where(total > 0, total, 1), 0.0)
            m = fit_ridge(frame, sel, y, share_features(stat, pos, groups), lo=0.0, hi=1.0)
            model.share[(pos, stat)] = m
            opp[stat] = m.predict(frame, sel) * team[stat]
        scale = _imp_scale(model, frame, sel)
        for stat, (opportunity, _, _) in STACKS.items():
            if pos not in STACK_POSITIONS[stat]:
                continue
            names, P = _products(frame, sel, stat, groups, opp[opportunity], team, scale)
            y = frame.stat(stat)[sel]
            A = P.T @ P
            ridge = 1e-3 * np.trace(A) / max(1, len(names))
            # lstsq: a stat with no opportunities at this position gives an all-zero design
            coef = np.linalg.lstsq(A + ridge * np.eye(len(names)), P.T @ y, rcond=None)[0]
            model.stack[(pos, stat)] = (names, coef)
    return model


def predict(model: Model, frame: Frame, mask: np.ndarray) -> np.ndarray:
    """Per-stat means (columns in STATS order) for rows in mask, conditional on playing."""
    out = np.zeros((int(mask.sum()), len(STATS)))
    where = np.flatnonzero(mask)
    for pos in POSITIONS:
        sub = frame.position[where] == pos
        if not sub.any():
            continue
        sel = np.zeros(len(frame.X), bool)
        sel[where[sub]] = True
        team = _team_volume(model, frame, sel)
        opp = {}
        for stat in SHARES:
            m = model.share.get((pos, stat))
            opp[stat] = m.predict(frame, sel) * team[stat] if m else np.zeros(int(sel.sum()))
        block = np.zeros((int(sel.sum()), len(STATS)))
        for stat in SHARES:
            block[:, STATS.index(stat)] = opp[stat]
        scale = _imp_scale(model, frame, sel)
        for stat in STACKS:
            fitted = model.stack.get((pos, stat))
            if fitted is None:
                continue
            names, P = _products(frame, sel, stat, model.groups, opp[STACKS[stat][0]], team, scale)
            block[:, STATS.index(stat)] = np.maximum(0.0, P @ fitted[1])
        touches = opp["targets"] + opp["rushing_attempts"] + 0.1 * opp["passing_attempts"]
        rf = frame.col("r_fumble")[sel]
        block[:, STATS.index("fumbles_lost")] = touches * np.where(np.isnan(rf), MINOR["fumbles_lost"], rf)
        for stat, base in (("passing_2pt_conversions", "passing_attempts"), ("rushing_2pt_conversions", "rushing_attempts"),
                           ("receiving_2pt_conversions", "targets")):
            block[:, STATS.index(stat)] = opp[base] * MINOR[stat]
        out[sub] = block
    return out


def add_league_rates(row: dict, rates: dict) -> None:
    """lg_* columns: the position's league rate, so each stack can learn its own shrinkage."""
    lr = rates[row["position"]]
    for name in RATES:
        row["lg_" + name] = lr[name]


def score(stat_matrix: np.ndarray, weights_by_stat: dict[str, float]) -> np.ndarray:
    w = np.array([weights_by_stat.get(s, 0.0) for s in STATS])
    return stat_matrix @ w
