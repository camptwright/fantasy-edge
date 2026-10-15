"""Records and features for projection engine v2, shared by the lab and serving.

The research lab (scripts/engine_lab.py, nflreadpy) and the worker (nflverse
release CSVs; the serving image has no nflreadpy, polars or pyarrow) feed
the same row dicts through `assemble`, so a model graded in the lab is the
model that runs. Values may arrive typed (nflreadpy) or as CSV strings.

Sleeper inputs are projections for games already played only (last week's,
and week 1's from week 2 on): Sleeper's archive revises a week's
projections with in-game news (docs/2026-10-15-engine-v2-plan.md, "Sleeper
archive leakage").
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.services import projection_engine_v2 as v2
from src.services.game_environment import implied_points

EASTERN = ZoneInfo("America/New_York")
FIRST_SEASON, TRAIN_FROM = 2019, 2020
LEAN = ("core", "offseason", "role", "availability", "sleeper_prev")
STAT_COLUMNS = {"targets": "targets", "receptions": "receptions", "receiving_yards": "receiving_yards",
                "receiving_tds": "receiving_touchdowns", "carries": "rushing_attempts",
                "rushing_yards": "rushing_yards", "rushing_tds": "rushing_touchdowns",
                "attempts": "passing_attempts", "completions": "passing_completions",
                "passing_yards": "passing_yards", "passing_tds": "passing_touchdowns",
                "passing_interceptions": "passing_interceptions",
                "passing_2pt_conversions": "passing_2pt_conversions",
                "rushing_2pt_conversions": "rushing_2pt_conversions",
                "receiving_2pt_conversions": "receiving_2pt_conversions"}
FUMBLES = ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")
SLEEPER_VOLUME = {"targets": "rec_tgt", "rushing_attempts": "rush_att", "passing_attempts": "pass_att"}
ON_ROSTER = ("ACT", "INA")
OFF_ROSTER = ("RES", "DEV", "CUT", "RET", "EXE", "TRD")


def num(v) -> float | None:
    if v is None or v == "" or v == "NA":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def whole(v) -> int | None:
    f = num(v)
    return int(f) if f is not None else None


def text(v) -> str | None:
    return None if v is None or v == "" or v == "NA" else str(v)


def kickoff(gameday: str, gametime: str | None) -> datetime:
    return datetime.fromisoformat(f"{gameday}T{gametime or '13:00'}").replace(tzinfo=EASTERN)


def sleeper_key(v) -> str | None:
    f = num(v)
    return str(int(f)) if f is not None else text(v)


# ---------------------------------------------------------------- assemble

def assemble(schedules, player_stats, snaps, rosters, playerids, sleeper: dict) -> dict:
    """Per-game records: games, team-games, player-games, rookies, rosters, Sleeper by gsis.

    sleeper: {(season, week): {sleeper_id: projection dict}}.
    """
    games = {}
    for g in schedules:
        season, week = whole(g["season"]), whole(g["week"])
        if g["game_type"] != "REG" or season is None or season < FIRST_SEASON:
            continue
        spread, total = num(g["spread_line"]), num(g["total_line"])
        home_spread = -spread if spread is not None else None
        hp, ap = implied_points(total, home_spread) if home_spread is not None and total is not None else (None, None)
        games[g["game_id"]] = {"season": season, "week": week, "kickoff": kickoff(g["gameday"], text(g["gametime"])),
                               "home": g["home_team"], "away": g["away_team"], "home_points": hp, "away_points": ap,
                               "home_spread": home_spread, "total": total, "final": num(g["home_score"]) is not None}
    players, team_tot = {}, defaultdict(lambda: defaultdict(float))
    for r in player_stats:
        g = games.get(r["game_id"])
        if g is None or not g["final"] or r["team"] not in (g["home"], g["away"]) or r.get("season_type", "REG") != "REG":
            continue
        stats = {stat: num(r[col]) or 0.0 for col, stat in STAT_COLUMNS.items()}
        stats["fumbles_lost"] = float(sum(num(r[c]) or 0.0 for c in FUMBLES))
        air = num(r.get("receiving_air_yards")) or 0.0
        players[(r["game_id"], r["player_id"])] = {
            "gsis": r["player_id"], "game_id": r["game_id"], "season": g["season"], "week": g["week"],
            "kickoff": g["kickoff"], "team": r["team"], "position": r["position"], "stats": stats, "air_yards": air}
        t = team_tot[(r["game_id"], r["team"])]
        t["targets"] += stats["targets"]
        t["carries"] += stats["rushing_attempts"]
        t["pass_att"] += stats["passing_attempts"]
        t["air_yards"] += max(0.0, air)
    pfr_to_gsis, sleeper_to_gsis, rookie, on_team, roster_status = {}, {}, {}, defaultdict(set), {}
    for r in rosters:
        gsis = text(r["gsis_id"])
        season, week = whole(r["season"]), whole(r["week"])
        if not gsis or season is None:
            continue
        if text(r["pfr_id"]):
            pfr_to_gsis[r["pfr_id"]] = gsis
        if sleeper_key(r["sleeper_id"]):
            sleeper_to_gsis[sleeper_key(r["sleeper_id"])] = gsis
        if whole(r["rookie_year"]) == season and whole(r["draft_number"]):
            rookie[(season, gsis)] = whole(r["draft_number"])
        if r["game_type"] == "REG" and week is not None:
            roster_status[(season, week, gsis)] = (r["team"], r["status"], r["position"])
            if r["status"] in ON_ROSTER:
                on_team[(season, week, r["team"])].add(gsis)
    for r in playerids:
        s, gsis = sleeper_key(r["sleeper_id"]), text(r["gsis_id"])
        if s and gsis:
            sleeper_to_gsis.setdefault(s, gsis)
    snap = {}
    for r in snaps:
        gsis = pfr_to_gsis.get(r["pfr_player_id"])
        if gsis and r["game_type"] == "REG":
            snap[(r["game_id"], gsis)] = num(r["offense_pct"]) or 0.0
    for key, p in players.items():
        tt = team_tot[(p["game_id"], p["team"])]
        p.update({"team_targets": tt["targets"], "team_carries": tt["carries"], "team_pass_att": tt["pass_att"],
                  "team_air_yards": tt["air_yards"], "snap_pct": snap.get(key)})
    teams = {}
    for (game_id, team), tt in team_tot.items():
        teams[(game_id, team)] = team_game(games[game_id], game_id, team, tt)
    by_gsis = {key: {sleeper_to_gsis[k]: v for k, v in week.items() if k in sleeper_to_gsis and isinstance(v, dict) and v}
               for key, week in sleeper.items()}
    return {"games": games, "teams": teams, "players": players, "rookie": rookie, "on_team": dict(on_team),
            "roster_status": roster_status, "sleeper": by_gsis, "sleeper_to_gsis": sleeper_to_gsis}


def team_game(g: dict, game_id: str, team: str, tt: dict | None) -> dict:
    home = team == g["home"]
    tt = tt or {}
    return {"game_id": game_id, "team": team, "opp": g["away"] if home else g["home"],
            "season": g["season"], "week": g["week"], "kickoff": g["kickoff"],
            "implied": g["home_points"] if home else g["away_points"],
            "spread": (g["home_spread"] if home else -g["home_spread"]) if g["home_spread"] is not None else None,
            "total": g["total"], "pass_att": tt.get("pass_att", 0.0), "carries": tt.get("carries", 0.0),
            "targets": tt.get("targets", 0.0), "plays": tt.get("plays", tt.get("pass_att", 0.0) + tt.get("carries", 0.0)),
            "dropbacks": tt.get("dropbacks", tt.get("pass_att", 0.0)), "proe": tt.get("proe")}


def availability(games: dict, injuries, rosters, depth_weekly, depth_snapshots) -> dict:
    """Pre-game availability: injury-report Out/Doubtful, off-roster status, depth-chart rank.

    depth_weekly: nflverse weekly charts (through 2024); depth_snapshots:
    timestamped charts (2025 on), read as the latest snapshot before each
    team's kickoff.
    """
    out_list = defaultdict(set)
    for r in injuries:
        if r["game_type"] == "REG" and r["report_status"] in ("Out", "Doubtful") and text(r["gsis_id"]):
            out_list[(whole(r["season"]), whole(r["week"]), r["team"])].add(r["gsis_id"])
    for r in rosters:
        if r["game_type"] == "REG" and text(r["gsis_id"]) and r["status"] in OFF_ROSTER:
            out_list[(whole(r["season"]), whole(r["week"]), r["team"])].add(r["gsis_id"])
    depth = {}
    for r in depth_weekly:
        if (r["formation"] == "Offense" and r["position"] in v2.POSITIONS and r["game_type"] == "REG"
                and text(r["gsis_id"]) and whole(r["depth_team"])):
            key = (whole(r["season"]), whole(r["week"]), r["club_code"], r["gsis_id"])
            depth[key] = min(depth.get(key, 99), whole(r["depth_team"]))
    kick = defaultdict(dict)
    for g in games.values():
        for team in (g["home"], g["away"]):
            kick[team][(g["season"], g["week"])] = g["kickoff"]
    by_team = defaultdict(lambda: defaultdict(dict))
    for r in depth_snapshots:
        if r["pos_abb"] in v2.POSITIONS and text(r["gsis_id"]) and whole(r["pos_rank"]):
            dt = datetime.fromisoformat(r["dt"].replace("Z", "+00:00"))
            cur = by_team[r["team"]][dt]
            cur[r["gsis_id"]] = min(cur.get(r["gsis_id"], 99), whole(r["pos_rank"]))
    for team, snaps in by_team.items():
        times = sorted(snaps)
        for (season, week), ko in kick.get(team, {}).items():
            if season < 2025:
                continue
            before = [t for t in times if t < ko]
            if before:
                for gsis, rank in snaps[before[-1]].items():
                    depth[(season, week, team, gsis)] = rank
    return {"out": dict(out_list), "depth": depth}


# ---------------------------------------------------------------- features

def vacated_volume(data: dict) -> dict:
    """(season, week, team) -> last season's target/carry share of players no longer on the active roster."""
    season_tot = defaultdict(lambda: defaultdict(float))
    player_tot = defaultdict(lambda: defaultdict(float))
    for p in data["players"].values():
        for stat in ("targets", "rushing_attempts"):
            season_tot[(p["season"], p["team"])][stat] += p["stats"][stat]
            player_tot[(p["season"], p["team"], p["gsis"])][stat] += p["stats"][stat]
    last = defaultdict(list)
    for (season, team, gsis), tot in player_tot.items():
        last[(season, team)].append((gsis, tot))
    out = {}
    for (season, week, team), roster in data["on_team"].items():
        prev, st = last.get((season - 1, team), []), season_tot.get((season - 1, team))
        if not prev or not st:
            continue
        out[(season, week, team)] = {stat: sum(t[stat] for g, t in prev if g not in roster) / st[stat] if st[stat] else 0.0
                                     for stat in ("targets", "rushing_attempts")}
    return out


def team_availability(data: dict, extra: dict, upcoming: list[tuple] = ()) -> dict:
    """(season, week, team) -> {position or '*': {out_<stat>, return_<stat>}} from teammates' recent shares.

    upcoming: extra (season, week, team, kickoff) keys to describe, for games not played yet.
    """
    by_team = defaultdict(list)
    for p in data["players"].values():
        by_team[p["team"]].append(p)
    played = defaultdict(list)  # (game, team): that team's players, never the opponent's
    for p in sorted(data["players"].values(), key=lambda p: p["kickoff"]):
        played[(p["game_id"], p["team"])].append(p)
    team_games = {team: sorted({(p["kickoff"], p["game_id"], p["season"], p["week"]) for p in ps})
                  for team, ps in by_team.items()}
    keys = [(team, i, g[2], g[3]) for team, gs in team_games.items() for i, g in enumerate(gs)]
    keys += [(team, None, season, week, ko) for season, week, team, ko in upcoming]
    out = {}
    for key in keys:
        team, season, week = key[0], key[2], key[3]
        gs = team_games.get(team, [])
        recent = gs[max(0, key[1] - 4):key[1]] if key[1] is not None else [g for g in gs if g[0] < key[4]][-4:]
        if not recent:
            continue
        last_ids = {p["gsis"] for p in played[(recent[-1][1], team)]}
        seen = defaultdict(list)
        for _, gid, _, _ in recent:
            for p in played[(gid, team)]:
                seen[p["gsis"]].append(p)
        listed = extra["out"].get((season, week, team), set())
        agg = defaultdict(lambda: defaultdict(float))
        for gsis, games_p in seen.items():
            if gsis in listed:
                kind = "out"
            elif gsis not in last_ids:
                kind = "return"
            else:
                continue
            pos = games_p[-1]["position"]
            for stat, team_key in v2.SHARES.items():
                shares = [g["stats"][stat] / g["team_" + team_key] for g in games_p[-3:] if g["team_" + team_key] > 0]
                share = sum(shares) / len(shares) if shares else 0.0
                for scope in ("*", pos):
                    agg[scope][f"{kind}_{stat}"] += share
        out[(season, week, team)] = {k: dict(v) for k, v in agg.items()}
    return out


def _team_index(data: dict):
    by_team = defaultdict(list)
    for t in sorted(data["teams"].values(), key=lambda t: t["kickoff"]):
        by_team[t["team"]].append(t)
    return by_team


def _team_features(data: dict, by_team: dict, t: dict, before: datetime) -> dict:
    prior = [x for x in by_team.get(t["team"], []) if x["kickoff"] < before]
    opp_seq = [x for x in by_team.get(t["opp"], []) if x["kickoff"] < before]
    allowed = [data["teams"][(x["game_id"], x["opp"])] for x in opp_seq if (x["game_id"], x["opp"]) in data["teams"]]
    return v2.team_features(prior, t, allowed)


def league_rates_by_season(data: dict, seasons) -> dict:
    players = list(data["players"].values())
    return {s: v2.league_rates([p for p in players if p["season"] < s or (s == FIRST_SEASON and p["season"] == s)])
            for s in seasons}


def sleeper_context(data: dict, season: int, week: int, gsis: str) -> tuple[dict | None, dict | None]:
    """(week-1 volume prior from week 2 on, previous played week's projection): past games only."""
    s1 = data["sleeper"].get((season, 1), {}).get(gsis) if week > 1 else None
    prev = next((data["sleeper"].get((season, w), {}).get(gsis) for w in range(week - 1, 0, -1)
                 if (data["sleeper"].get((season, w), {}).get(gsis) or {}).get("gp")), None)
    return s1, prev


def player_row(data, extra, vacated, avail, rates, prior: list[dict], target: dict, tf: dict) -> dict:
    gsis = target["gsis"]
    s1, prev = sleeper_context(data, target["season"], target["week"], gsis)
    ctx = {"sleeper_w1": {k: num(s1.get(c)) or 0.0 for k, c in SLEEPER_VOLUME.items()} if s1 else None,
           "rookie_pick": data["rookie"].get((target["season"], gsis)),
           "vacated": vacated.get((target["season"], target["week"], target["team"])),
           "availability": avail.get((target["season"], target["week"], target["team"]), {}),
           "depth_rank": extra["depth"].get((target["season"], target["week"], target["team"], gsis))}
    row = v2.player_features(prior, target, ctx, rates[target["season"]])
    row.update(tf)
    for stat, col in SLEEPER_VOLUME.items():
        row[f"sl_prev_{stat}"] = (num(prev.get(col)) or 0.0) / v2.VOLUME_DENOM[stat] if prev else math.nan
    row["sl_prev_missing"] = float(prev is None)
    row["position"] = target["position"]
    v2.add_league_rates(row, rates[target["season"]])
    return row


def features(data: dict, extra: dict, sleeper_weights: dict | None = None) -> tuple[list[dict], list]:
    """Team rows and (player row, meta) pairs for every played player-game from TRAIN_FROM."""
    by_team = _team_index(data)
    team_rows, team_feat = [], {}
    for team, seq in by_team.items():
        for t in seq:
            if t["implied"] is None:
                continue
            f = _team_features(data, by_team, t, t["kickoff"])
            team_feat[(t["game_id"], team)] = f
            team_rows.append({**f, "season": t["season"], "week": t["week"], "kickoff": t["kickoff"],
                              "pass_att": t["pass_att"], "carries": t["carries"]})
    by_player = defaultdict(list)
    for p in sorted(data["players"].values(), key=lambda p: p["kickoff"]):
        by_player[p["gsis"]].append(p)
    seasons = sorted({p["season"] for p in data["players"].values()})
    rates = league_rates_by_season(data, seasons)
    vacated, avail = vacated_volume(data), team_availability(data, extra)
    rows = []
    for gsis, seq in by_player.items():
        for i, p in enumerate(seq):
            if p["position"] not in v2.POSITIONS or p["season"] < TRAIN_FROM:
                continue
            tf = team_feat.get((p["game_id"], p["team"]))
            if tf is None:
                continue
            row = player_row(data, extra, vacated, avail, rates, seq[:i], p, tf)
            row.update({"stats": p["stats"], "team_targets": p["team_targets"], "team_carries": p["team_carries"],
                        "team_pass_att": p["team_pass_att"]})
            sl = data["sleeper"].get((p["season"], p["week"]), {}).get(gsis)
            meta = {"gsis": gsis, "game_id": p["game_id"], "season": p["season"], "week": p["week"],
                    "kickoff": p["kickoff"], "team": p["team"],
                    "sleeper": sum((num(sl.get(k)) or 0.0) * w for k, w in sleeper_weights.items())
                    if sl and sleeper_weights else None}
            rows.append((row, meta))
    return team_rows, rows


def target_rows(data: dict, extra: dict, targets: list[dict]) -> tuple[list[dict], list[dict]]:
    """Feature rows for games not yet played.

    targets: {game_id, season, week, kickoff, team, opp, home, implied, spread,
    total, gsis, position}, one per candidate player.
    """
    by_team = _team_index(data)
    by_player = defaultdict(list)
    for p in sorted(data["players"].values(), key=lambda p: p["kickoff"]):
        by_player[p["gsis"]].append(p)
    rates = league_rates_by_season(data, sorted({t["season"] for t in targets}))
    vacated = vacated_volume(data)
    avail = team_availability(data, extra, sorted({(t["season"], t["week"], t["team"], t["kickoff"]) for t in targets}))
    team_rows, rows, cache = [], [], {}
    for t in targets:
        key = (t["game_id"], t["team"])
        if key not in cache:
            tg = {"team": t["team"], "opp": t["opp"], "implied": t["implied"], "spread": t["spread"], "total": t["total"]}
            cache[key] = _team_features(data, by_team, tg, t["kickoff"])
            team_rows.append(cache[key])
        prior = [p for p in by_player.get(t["gsis"], []) if p["kickoff"] < t["kickoff"]]
        rows.append(player_row(data, extra, vacated, avail, rates, prior, t, cache[key]))
    return team_rows, rows


# ---------------------------------------------------------------- downloads (serving)

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
SOURCES = {
    "player_stats": RELEASES + "/stats_player/stats_player_week_{season}.csv",
    "snap_counts": RELEASES + "/snap_counts/snap_counts_{season}.csv",
    "rosters": RELEASES + "/weekly_rosters/roster_weekly_{season}.csv",
    "injuries": RELEASES + "/injuries/injuries_{season}.csv",
    "depth_charts": RELEASES + "/depth_charts/depth_charts_{season}.csv",
    "schedules": "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
    "playerids": "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv",
}
SLEEPER = "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"


def _fetch(url: str, path: Path, max_age: timedelta | None) -> bytes:
    """Cached GET; max_age None keeps a cached copy forever (completed seasons)."""
    import httpx
    if path.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if max_age is None or age <= max_age:
            return path.read_bytes()
    response = httpx.get(url, follow_redirects=True, timeout=120)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(response.content)
    tmp.replace(path)
    return response.content


def csv_rows(name: str, cache: Path, season: int | None, current: int) -> list[dict]:
    url = SOURCES[name].format(season=season)
    fresh = None if season is not None and season < current else timedelta(hours=6)
    body = _fetch(url, cache / f"{name}_{season or 'all'}.csv", fresh)
    return list(csv.DictReader(io.StringIO(body.decode("utf-8"))))


def sleeper_weeks(cache: Path, keys: list[tuple[int, int]], current: int) -> dict:
    out = {}
    for season, week in keys:
        body = _fetch(SLEEPER.format(season=season, week=week), cache / "sleeper" / f"{season}_{week}.json",
                      None if season < current else timedelta(hours=6))
        out[(season, week)] = json.loads(body)
    return out


def load_release(cache: Path, current: int) -> tuple[dict, dict]:
    """data and availability from nflverse release CSVs and Sleeper's archive, FIRST_SEASON..current."""
    seasons = list(range(FIRST_SEASON, current + 1))
    schedules = csv_rows("schedules", cache, None, current)
    stats, snaps, rosters, injuries, weekly, snapshots = [], [], [], [], [], []
    for s in seasons:
        stats += csv_rows("player_stats", cache, s, current)
        snaps += csv_rows("snap_counts", cache, s, current)
        rosters += csv_rows("rosters", cache, s, current)
        injuries += csv_rows("injuries", cache, s, current)
        (weekly if s <= 2024 else snapshots).extend(csv_rows("depth_charts", cache, s, current))
    played = sorted({(whole(g["season"]), whole(g["week"])) for g in schedules
                     if g["game_type"] == "REG" and num(g["home_score"]) is not None
                     and (whole(g["season"]) or 0) >= TRAIN_FROM})
    keys = sorted(set(played) | {(s, 1) for s in seasons})
    sleeper = sleeper_weeks(cache, keys, current)
    data = assemble(schedules, stats, snaps, rosters, csv_rows("playerids", cache, None, current), sleeper)
    extra = availability(data["games"], injuries, rosters, weekly, snapshots)
    return data, extra
