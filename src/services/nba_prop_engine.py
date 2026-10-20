"""NBA player-stat projections and prop probabilities (research).

Per player and game, from strictly earlier games only:
- minutes: recency-weighted mean (half-life HALF_LIFE games; last season's
  games count CARRYOVER as much), conditional on playing;
- per-minute rate per stat: the same weights, shrunk toward the position
  group's (G/F/C) league rate with SHRINK_MINUTES of prior;
- base mean = minutes x rate, then a fitted multiplier per stat
  exp(k + a*log(total/LEAGUE_TOTAL) + b*|spread| + c*log(opponent factor)),
  where the opponent factor is what that defense allowed this position
  group per game relative to the league (shrunk, earlier games only).
Combos (PRA etc.) are sums of the component means. P(over) uses the
empirical actual/mean ratio quantiles per stat and mean tercile.

Coefficients and quantiles are fitted by scripts/research_nba_props.py on
2025-26 (walk-forward) into config/nba_prop_model.json. Research only: the
prop board shows it beside the no-vig market and never makes a prop
actionable.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

CONFIG = Path(__file__).resolve().parents[2] / "config" / "nba_prop_model.json"
BASE = ("points", "rebounds", "assists", "three_pointers_made", "steals", "blocks", "turnovers")
COMBOS = {"points_rebounds_assists": ("points", "rebounds", "assists"), "points_rebounds": ("points", "rebounds"),
          "points_assists": ("points", "assists"), "rebounds_assists": ("rebounds", "assists"),
          "steals_blocks": ("steals", "blocks")}
STATS = BASE + tuple(COMBOS)
GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}
HALF_LIFE = 10.0
CARRYOVER = 0.5
SHRINK_MINUTES = 150.0
LEAGUE_TOTAL = 229.0
DEFENSE_PRIOR_GAMES = 10.0


@dataclass
class Played:
    game_id: str
    time: object
    season: int
    team: str
    opponent: str
    started: bool
    stats: dict
    total: float | None = None
    spread: float | None = None  # this player's team handicap; negative = favoured


@dataclass
class League:
    """Running position-group rates and defense-allowed totals from earlier games."""
    stat_sums: dict = field(default_factory=lambda: defaultdict(float))  # (group, stat) -> sum
    minute_sums: dict = field(default_factory=lambda: defaultdict(float))  # group -> minutes
    allowed: dict = field(default_factory=lambda: defaultdict(float))  # (defense, group, stat) -> sum
    allowed_games: dict = field(default_factory=lambda: defaultdict(set))  # (defense, group) -> game ids
    group_games: dict = field(default_factory=lambda: defaultdict(set))  # group -> (game, defense) pairs

    def add(self, group: str, defense: str, game_id: str, stats: dict) -> None:
        self.minute_sums[group] += stats.get("minutes", 0.0)
        for s in BASE:
            v = stats.get(s, 0.0)
            self.stat_sums[(group, s)] += v
            self.allowed[(defense, group, s)] += v
        self.allowed_games[(defense, group)].add(game_id)
        self.group_games[group].add((game_id, defense))

    def rate(self, group: str, stat: str) -> float | None:
        m = self.minute_sums.get(group, 0.0)
        return self.stat_sums.get((group, stat), 0.0) / m if m > 0 else None

    def opponent_factor(self, defense: str, group: str, stat: str) -> float:
        pairs = len(self.group_games.get(group, ()))
        if not pairs:
            return 1.0
        league = self.stat_sums.get((group, stat), 0.0) / pairs  # allowed per defense-game
        games = len(self.allowed_games.get((defense, group), ()))
        if league <= 0:
            return 1.0
        mine = self.allowed.get((defense, group, stat), 0.0)
        return (mine + DEFENSE_PRIOR_GAMES * league) / ((games + DEFENSE_PRIOR_GAMES) * league)


def base_projection(prior: list[Played], group: str, league: League, season: int, *,
                    half_life: float = HALF_LIFE, shrink: float = SHRINK_MINUTES) -> dict | None:
    """Minutes and base per-stat means from earlier games (newest last)."""
    played = [p for p in prior if p.stats.get("minutes", 0) > 0][-82:]
    if not played:
        return None
    w = np.array([0.5 ** ((len(played) - 1 - i) / half_life) * (1.0 if p.season == season else CARRYOVER)
                  for i, p in enumerate(played)])
    minutes = np.array([p.stats["minutes"] for p in played])
    projected = float((w * minutes).sum() / w.sum())
    weighted_minutes = float((w * minutes).sum())
    out = {"minutes": projected, "games": len(played)}
    for s in BASE:
        prior_rate = league.rate(group, s)
        if prior_rate is None:
            return None
        made = float((w * np.array([p.stats.get(s, 0.0) for p in played])).sum())
        out[s] = projected * (made + shrink * prior_rate) / (weighted_minutes + shrink)
    return out


def features(total: float | None, spread: float | None, opponent: float) -> np.ndarray:
    return np.array([1.0, math.log(total / LEAGUE_TOTAL) if total else 0.0, abs(spread) if spread is not None else 0.0,
                     math.log(max(opponent, 1e-6))])


def adjust(base: dict, total, spread, league: League, defense: str, group: str, coefficients: dict) -> dict:
    out = {"minutes": base["minutes"]}
    for s in BASE:
        coef = np.array(coefficients.get(s, (0.0, 0.0, 0.0, 0.0)))
        out[s] = base[s] * math.exp(float(coef @ features(total, spread, league.opponent_factor(defense, group, s))))
    for combo, parts in COMBOS.items():
        out[combo] = sum(out[p] for p in parts)
    return out


@lru_cache(maxsize=1)
def load() -> dict | None:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else None


def over_probability(stat: str, mean: float, line: float, artifact: dict | None = None) -> float | None:
    """P(actual > line) from the fitted actual/mean ratio quantiles for this stat and mean tercile."""
    spec = ((artifact or load()) or {}).get("distribution", {}).get(stat)
    if spec is None or mean is None or mean <= 0:
        return None
    edges = spec["edges"]
    q = np.array(spec["quantiles"][0 if mean < edges[0] else 1 if mean < edges[1] else 2])
    levels = np.linspace(0, 1, len(q))
    return float(1 - np.interp(line / mean, q, levels, left=0.0, right=1.0))


MARKET_ORDER = ("pinnacle", "bovada", "espn")


async def current_lines(db, game_ids) -> dict:
    """{game_id: (total, home spread)} from the latest pregame line, Pinnacle first."""
    from sqlalchemy import select
    from src.models.facts import TeamMarketLine
    rows = (await db.execute(select(TeamMarketLine).where(TeamMarketLine.game_id.in_(list(game_ids)),
            TeamMarketLine.market.in_(("total", "spread")), TeamMarketLine.side.in_(("over", "home")))
            .order_by(TeamMarketLine.observed_at.desc()))).scalars().all()
    latest = {}
    for r in rows:
        latest.setdefault((r.game_id, r.market, r.source), r.line)
    out = {}
    for gid in game_ids:
        pick = lambda market: next((latest[(gid, market, s)] for s in MARKET_ORDER if latest.get((gid, market, s)) is not None), None)  # noqa: E731
        out[gid] = (pick("total"), pick("spread"))
    return out


async def project(db, upcoming, now) -> dict:
    """{(player_id, game_id): {stat: mean, minutes, games}} for scheduled games, from final games before `now`.

    Players are bound to a game by their current roster team (src/ingest/nba_players.py).
    """
    from sqlalchemy import select
    from src.models.facts import Game, PlayerGameStat
    from src.models.identity import Player
    from src.services.nba_context import player_teams
    artifact = load()
    if not artifact or not upcoming:
        return {}
    season = max(g.season for g in upcoming)
    context = await player_teams(db, now=now)
    past = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.sport == "nba", Game.status == "final",
            Game.season.in_((season - 1, season)), Game.game_time.is_not(None), Game.game_time < now))).all()}
    rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type, PlayerGameStat.value)
            .where(PlayerGameStat.game_id.in_([g.id for g in past.values()])))).all()
    players = (await db.scalars(select(Player).where(Player.sport == "nba"))).all()
    groups = {str(p.id): GROUP.get(p.position) for p in players}
    stats = defaultdict(dict)
    for pid, gid, stat, value in rows:
        stats[(str(gid), str(pid))][stat] = float(value)
    by_game = defaultdict(list)
    for (gid, pid), s in stats.items():
        by_game[gid].append((pid, s))
    history, league = defaultdict(list), League()
    for gid in sorted(by_game, key=lambda g: past[g].game_time):
        g, ctx = past[gid], context.get(gid)
        if ctx is None:
            continue
        home, away = str(g.home_team_id), str(g.away_team_id)
        for pid, s in by_game[gid]:
            team, group = ctx["players"].get(pid), groups.get(pid)
            if team not in (home, away) or group is None or "minutes" not in s:
                continue
            opponent = away if team == home else home
            history[pid].append(Played(gid, g.game_time, g.season, team, opponent, pid in ctx["starters"], s))
            if s["minutes"] > 0:
                league.add(group, opponent, gid, s)
    lines = await current_lines(db, [g.id for g in upcoming])
    out = {}
    for g in upcoming:
        total, home_spread = lines.get(g.id, (None, None))
        for p in players:
            if p.current_team_id not in (g.home_team_id, g.away_team_id) or groups.get(str(p.id)) is None:
                continue
            group = groups[str(p.id)]
            base = base_projection(history.get(str(p.id), []), group, league, g.season,
                                   half_life=artifact["half_life"], shrink=artifact["shrink_minutes"])
            if base is None or base["games"] < 3:
                continue
            home = p.current_team_id == g.home_team_id
            spread = None if home_spread is None else (home_spread if home else -home_spread)
            defense = str(g.away_team_id if home else g.home_team_id)
            out[(p.id, g.id)] = {**adjust(base, total, spread, league, defense, group, artifact["coefficients"]),
                                 "games": base["games"], "total": total, "spread": spread}
    return out
