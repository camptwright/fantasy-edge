"""Player-prop board: line shopping against a no-vig consensus, plus trends.

Reconstructed from the published methods of the prop tools people use:
- OddsJam / Unabated style value: de-vig every book's two-sided price at the
  same line, average them into a consensus fair probability, then compare
  the best available price on each side (EV% = fair x decimal - 1). Pinnacle
  is not treated as uniquely sharp for props (it often does not post them,
  and its prop lines are not demonstrably sharper), so books weigh equally.
- Props.Cash / Outlier style context: hit rates over the last 5 and 10
  games, the season and against this opponent, and the opponent's rank
  allowing this stat to this position ("D vs Pos", 1 = allows the most).
- The projection engine's P(over) where it exists (research comparison).

A board row is research, not a bet: the consensus is only as good as the
books it averages, and stale or one-book lines are flagged rather than hidden.
Tracked picks (ev >= TRACK_EV with >= TRACK_BOOKS) are frozen when first
seen, closed at the last consensus before kickoff (CLV), then graded.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from src.models.facts import Game, PlayerGameStat, PlayerPropLine
from src.models.governance import DerivedCheckpoint
from src.models.identity import Player, Team
from src.services import prop_engine
from src.services.forecast_evidence import digest
from src.services.sharp_pricing import brand
from src.utils.odds_math import american_to_decimal, american_to_implied, remove_vig_two_way

SPORTS = ("nfl", "ncaaf")
FRESH = timedelta(hours=12)        # quotes older than this are dropped
REFRESH = timedelta(minutes=9)
TRACK_EV = 0.03
TRACK_BOOKS = 3
TRACK_LIMIT = 3000
STATS = {"passing_yards", "passing_attempts", "passing_completions", "passing_touchdowns", "passing_interceptions",
         "rushing_yards", "rushing_attempts", "receptions", "receiving_yards"}
EXCLUDED_BOOKS = {"underdog", "prizepicks"}  # DFS pick'em, not priced two-way offers


def board_name(sport: str) -> str:
    return f"prop_board:{sport}"


def tracker_name(sport: str) -> str:
    return f"prop_tracker:{sport}"


def valid_price(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and abs(v) >= 100


def ev(probability: float | None, price: int | None) -> float | None:
    if probability is None or not valid_price(price):
        return None
    return round(probability * american_to_decimal(price) - 1, 4)


def consensus(offers: list[dict]) -> dict:
    """offers: [{book, line, over, under, observed_at}] for one player/game/stat (latest per book).

    The main line is the one the most books price on both sides (ties go to the
    line nearest the median). Fair probability averages each two-sided book's
    de-vigged over probability at that line; best prices may come from any book
    at that line, one-sided or not.
    """
    two_sided = [o for o in offers if valid_price(o.get("over")) and valid_price(o.get("under"))]
    if not offers:
        return {"line": None, "books": 0}
    pool = two_sided or offers
    counts = Counter(o["line"] for o in pool)
    mid = median(o["line"] for o in pool)
    line = min(counts, key=lambda ln: (-counts[ln], abs(ln - mid), ln))
    at_line = [o for o in offers if o["line"] == line]
    fair = [remove_vig_two_way(o["over"], o["under"])[0] for o in at_line if o in two_sided]
    hold = [american_to_implied(o["over"]) + american_to_implied(o["under"]) - 1 for o in at_line if o in two_sided]
    fair_over = sum(fair) / len(fair) if fair else None

    def best(side):
        priced = [o for o in at_line if valid_price(o.get(side))]
        if not priced:
            return None
        top = max(priced, key=lambda o: (american_to_decimal(o[side]), o["book"]))
        return {"book": top["book"], "price": top[side]}

    over, under = best("over"), best("under")
    fair_under = 1 - fair_over if fair_over is not None else None
    return {"line": line, "books": len(fair), "quoted": len(at_line), "fair_over": round(fair_over, 4) if fair_over is not None else None,
            "spread": round(max(fair) - min(fair), 4) if len(fair) > 1 else None,
            "hold": round(sum(hold) / len(hold), 4) if hold else None,
            "best_over": over, "best_under": under,
            "ev_over": ev(fair_over, over and over["price"]), "ev_under": ev(fair_under, under and under["price"]),
            "other_lines": sorted({o["line"] for o in offers} - {line})}


def hit_rates(history: list[tuple[datetime, float, str | None]], line: float, season_start: datetime | None,
              opponent: str | None) -> dict:
    """history: [(kickoff, value, opponent code)] newest first. Hit = strictly over the line."""
    def rate(values):
        values = list(values)
        return {"hits": sum(v > line for v in values), "games": len(values)} if values else None
    values = [v for _, v, _ in history]
    return {"l5": rate(values[:5]), "l10": rate(values[:10]),
            "season": rate(v for t, v, _ in history if season_start and t >= season_start),
            "vs_opponent": rate(v for _, v, o in history if opponent and o == opponent),
            "average_l10": round(sum(values[:10]) / len(values[:10]), 1) if values else None,
            "last5": [round(v, 1) for v in values[:5]]}


def dvp_ranks(per_game: dict) -> dict:
    """per_game: {(defense, position, stat): [allowed per game]} -> {(defense, position, stat): (rank, teams)}; 1 = allows most."""
    grouped = defaultdict(dict)
    for (defense, pos, stat), values in per_game.items():
        if values:
            grouped[(pos, stat)][defense] = sum(values) / len(values)
    out = {}
    for (pos, stat), by_defense in grouped.items():
        ordered = sorted(by_defense.items(), key=lambda kv: (-kv[1], str(kv[0])))
        for rank, (defense, _) in enumerate(ordered, 1):
            out[(defense, pos, stat)] = (rank, len(ordered))
    return out


def score(row: dict) -> float:
    """Sort key: the better side's EV, discounted when the consensus is thin."""
    best = max([v for v in (row["ev_over"], row["ev_under"]) if v is not None], default=-1.0)
    return best - (0.02 if row["books"] < 3 else 0.0)


async def _quotes(db, sport: str, now: datetime):
    return (await db.execute(select(PlayerPropLine, Player, Game)
        .join(Player, Player.id == PlayerPropLine.player_id).join(Game, Game.id == PlayerPropLine.game_id)
        .where(Game.sport == sport, Game.status == "scheduled", Game.game_time.is_not(None), Game.game_time > now,
               Game.game_time <= now + timedelta(days=8), PlayerPropLine.observed_at >= now - FRESH,
               PlayerPropLine.stat_type.in_(STATS))
        .distinct(PlayerPropLine.player_id, PlayerPropLine.game_id, PlayerPropLine.stat_type, PlayerPropLine.source)
        .order_by(PlayerPropLine.player_id, PlayerPropLine.game_id, PlayerPropLine.stat_type, PlayerPropLine.source,
                  PlayerPropLine.observed_at.desc()))).all()


async def _history(db, sport: str, player_ids: set, now: datetime, season: int):
    """{player: [(kickoff, game, stat, value)]} for final games of this and last season, newest first."""
    rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.stat_type, PlayerGameStat.value, Game)
        .join(Game, Game.id == PlayerGameStat.game_id)
        .where(PlayerGameStat.player_id.in_(player_ids), PlayerGameStat.stat_type.in_(STATS), Game.sport == sport,
               Game.status == "final", Game.season.in_([season - 1, season]), Game.game_time.is_not(None),
               Game.game_time < now, or_(Game.game_type.is_(None), Game.game_type == "REG")))).all()
    out = defaultdict(list)
    for pid, stat, value, game in rows:
        out[pid].append((game.game_time, game, stat, value))
    for v in out.values():
        v.sort(key=lambda r: r[0], reverse=True)
    return out


async def _nfl_context(db, now: datetime, season: int):
    """(team of player in a game, D-vs-Pos ranks) from the engine's history loader (snap-count teams)."""
    from src.services.projection_engine import load_history
    history = await load_history(db, [season - 1, season], now)
    team_of = {(p.player_id, p.game_id): p.team_id for p in history.players.values()}
    latest_team = {}
    for p in sorted(history.players.values(), key=lambda p: p.kickoff):
        latest_team[p.player_id] = p.team_id
    per_game = defaultdict(lambda: defaultdict(float))  # (defense, pos, stat) -> game -> allowed
    seasons = defaultdict(lambda: {"now": [], "before": []})
    for p in history.players.values():
        pos, g = history.positions.get(p.player_id), history.games.get(p.game_id)
        if pos not in ("QB", "RB", "WR", "TE") or g is None:
            continue
        defense = g.away_team_id if p.team_id == g.home_team_id else g.home_team_id
        for stat, value in p.stats.items():
            if stat in STATS:
                per_game[(defense, pos, stat)][p.game_id] += value
    for key, games in per_game.items():
        for gid, allowed in games.items():
            seasons[key]["now" if history.games[gid].season == season else "before"].append(allowed)
    allowed = {k: (v["now"] if len(v["now"]) >= 4 else v["now"] + v["before"][-8:]) for k, v in seasons.items()}
    return team_of, latest_team, dvp_ranks(allowed)


async def build(db, sport: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    quotes = await _quotes(db, sport, now)
    groups = defaultdict(list)
    meta = {}
    for q, player, game in quotes:
        book = brand(q.source)
        if book in EXCLUDED_BOOKS or not isinstance(q.line, (int, float)) or not math.isfinite(q.line):
            continue
        key = (player.id, game.id, q.stat_type)
        groups[key].append({"book": book, "line": float(q.line), "over": q.over_price_american,
                            "under": q.under_price_american, "observed_at": q.observed_at.isoformat()})
        meta[key] = (player, game)
    if not groups:
        return {"status": "research", "sport": sport, "generated_at": now.isoformat(), "rows": [], "books": []}
    season = min(g.season for _, g in meta.values())
    teams = {t.id: t for t in (await db.scalars(select(Team).where(Team.sport == sport))).all()}
    code = lambda tid: (teams[tid].nflverse_abbr or teams[tid].name) if tid in teams else None  # noqa: E731
    history = await _history(db, sport, {k[0] for k in groups}, now, season)
    team_of, latest_team, dvp = ({}, {}, {})
    if sport == "nfl":
        team_of, latest_team, dvp = await _nfl_context(db, now, season)
    engine_stats, engine_artifact = {}, None
    if sport == "nfl":
        from src.services.engine_research import latest as engine_latest
        engine_artifact = prop_engine.load()
        checkpoint = await engine_latest(db)
        if engine_artifact and checkpoint and checkpoint.get("status") == "research":
            engine_stats = prop_engine.engine_stats(checkpoint)
    season_start = min((g.game_time for g in (r[1] for v in history.values() for r in v) if g.season == season), default=None)
    rows, books = [], Counter()
    for key, offers in groups.items():
        player, game = meta[key]
        stat = key[2]
        c = consensus(offers)
        if c["line"] is None:
            continue
        for o in offers:
            books[o["book"]] += 1
        team = latest_team.get(player.id) or player.current_team_id
        if team not in (game.home_team_id, game.away_team_id):
            team = None
        opponent = (game.away_team_id if team == game.home_team_id else game.home_team_id) if team else None
        past = []
        for kickoff, g, s, value in history.get(player.id, []):
            if s != stat:
                continue
            t = team_of.get((player.id, g.id)) or team
            opp = (g.away_team_id if t == g.home_team_id else g.home_team_id) if t in (g.home_team_id, g.away_team_id) else None
            past.append((kickoff, value, code(opp) if opp else None))
        hits = hit_rates(past, c["line"], season_start, code(opponent) if opponent else None)
        rank = dvp.get((opponent, player.position, stat)) if opponent else None
        engine = None
        projected = engine_stats.get((str(player.id), str(game.id)), {}).get(stat)
        if projected and engine_artifact and stat in prop_engine.STATS:
            p = prop_engine.over_probability(stat, projected, c["line"], engine_artifact)
            if p is not None:
                engine = {"projection": round(projected, 1), "over_probability": round(p, 3)}
        home, away = code(game.home_team_id), code(game.away_team_id)
        row = {"key": f"{player.id}:{game.id}:{stat}", "sport": sport, "game_id": str(game.id), "game_time": game.game_time.isoformat(),
               "matchup": f"{away or '?'} @ {home or '?'}", "player_id": str(player.id), "player": player.full_name,
               "position": player.position, "team": code(team) if team else None, "opponent": code(opponent) if opponent else None,
               "stat": stat, **c, "hit": hits, "engine": engine,
               "dvp": {"rank": rank[0], "teams": rank[1]} if rank else None,
               "offers": sorted(offers, key=lambda o: (o["line"], o["book"])),
               "last_seen": max(o["observed_at"] for o in offers)}
        row["score"] = round(score(row), 4)
        rows.append(row)
    rows.sort(key=lambda r: (-r["score"], r["key"]))
    return {"status": "research", "sport": sport, "generated_at": now.isoformat(), "rows": rows,
            "books": sorted(books), "method": "no-vig consensus of every book at the main line; EV at the best price per side"}


def track(tracker: dict, board: dict, results: dict, now: datetime) -> dict:
    """Freeze new value picks, update closing consensus for unstarted games, grade finished ones.

    results: {(player_id, game_id, stat): value} for final games.
    """
    picks = {p["id"]: p for p in tracker.get("picks", [])}
    current = {r["key"]: r for r in board.get("rows", [])}
    for r in board.get("rows", []):
        for side in ("over", "under"):
            value, best = r[f"ev_{side}"], r[f"best_{side}"]
            pid = f"{r['key']}:{side}:{r['line']}"
            if value is None or value < TRACK_EV or r["books"] < TRACK_BOOKS or pid in picks:
                continue
            fair = r["fair_over"] if side == "over" else 1 - r["fair_over"]
            picks[pid] = {"id": pid, "key": r["key"], "player": r["player"], "stat": r["stat"], "side": side, "line": r["line"],
                          "book": best["book"], "price": best["price"], "fair": round(fair, 4), "ev": value, "books": r["books"],
                          "game_time": r["game_time"], "first_seen": now.isoformat(), "close_fair": None, "result": None}
    for p in picks.values():
        r = current.get(p["key"])
        if p["result"] is None and r and r["line"] == p["line"] and r["fair_over"] is not None and datetime.fromisoformat(p["game_time"]) > now:
            p["close_fair"] = round(r["fair_over"] if p["side"] == "over" else 1 - r["fair_over"], 4)
        if p["result"] is None:
            player_id, game_id, stat = p["key"].split(":")
            actual = results.get((player_id, game_id, stat))
            if actual is not None:
                won = actual > p["line"] if p["side"] == "over" else actual < p["line"]
                p["actual"] = actual
                p["result"] = "push" if actual == p["line"] else "win" if won else "loss"
    ordered = sorted(picks.values(), key=lambda p: p["first_seen"])[-TRACK_LIMIT:]
    return {"picks": ordered, "summary": summary(ordered), "updated_at": now.isoformat()}


def summary(picks: list[dict]) -> dict:
    graded = [p for p in picks if p["result"] in ("win", "loss")]
    profit = sum(american_to_decimal(p["price"]) - 1 if p["result"] == "win" else -1 for p in graded)
    clv = [p["close_fair"] - american_to_implied(p["price"]) for p in picks if p.get("close_fair") is not None]
    return {"tracked": len(picks), "graded": len(graded), "wins": sum(p["result"] == "win" for p in graded),
            "units": round(profit, 2), "roi": round(profit / len(graded), 4) if graded else None,
            "expected_roi": round(sum(p["ev"] for p in graded) / len(graded), 4) if graded else None,
            "average_clv": round(sum(clv) / len(clv), 4) if clv else None, "clv_n": len(clv),
            "beat_close": round(sum(c > 0 for c in clv) / len(clv), 3) if clv else None}


async def _results(db, picks: list[dict]) -> dict:
    keys = [p["key"].split(":") for p in picks if p["result"] is None]
    if not keys:
        return {}
    rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type, PlayerGameStat.value)
        .join(Game, Game.id == PlayerGameStat.game_id)
        .where(Game.status == "final", PlayerGameStat.game_id.in_({k[1] for k in keys}),
               PlayerGameStat.player_id.in_({k[0] for k in keys})))).all()
    return {(str(p), str(g), s): v for p, g, s, v in rows}


async def _save(db, name: str, payload: dict, now: datetime):
    values = {"name": name, "digest": digest(payload), "payload": payload, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))


async def refresh(db, *, now: datetime | None = None, force: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {}
    for sport in SPORTS:
        row = await db.get(DerivedCheckpoint, board_name(sport))
        if row and not force and now - datetime.fromisoformat(row.payload["generated_at"]) < REFRESH:
            out[sport] = "fresh"
            continue
        board = await build(db, sport, now=now)
        await _save(db, board_name(sport), board, now)
        tracker_row = await db.get(DerivedCheckpoint, tracker_name(sport))
        tracker = tracker_row.payload if tracker_row else {"picks": []}
        updated = track(tracker, board, await _results(db, tracker.get("picks", [])), now)
        await _save(db, tracker_name(sport), updated, now)
        await db.commit()
        out[sport] = {"rows": len(board["rows"]), "tracked": updated["summary"]["tracked"]}
    return out


async def latest(db, sport: str) -> dict | None:
    row = await db.get(DerivedCheckpoint, board_name(sport))
    return row.payload if row else None


async def tracker(db, sport: str) -> dict | None:
    row = await db.get(DerivedCheckpoint, tracker_name(sport))
    return row.payload if row else None
