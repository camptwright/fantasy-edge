"""Full-pool prospective grading: every projected player, not only rostered ones.

The rostered-player harness (projection_engine_prospective.report) pairs the
challengers with Sleeper only where a league roster holds the player and the
platform reports his points: about 40 graded rows a week, so the consensus
(about 0.15 points better than Sleeper in the 2026 retrospective) would need
most of the season to qualify. FantasyPros grades on the pool of projected
top-N plus actual top-N at each position, which by construction includes
players on nobody's roster. This module grades that pool:

- capture: freezes Sleeper's own weekly stat projections (the full payload the
  Sleeper sync already stores) for every QB/RB/WR/TE whose game kicks off in
  the next CAPTURE_WINDOW, create-only, so the baseline is Sleeper as of a few
  hours before kickoff (at least as current as the challengers' captures);
- report: scores the frozen Sleeper, ESPN and engine-v1 projections and the
  box-score result with each Sleeper league's rules, pairs every challenger
  with Sleeper on the same rows, and applies the same promotion check
  (starter pool per league, week-block bootstrap, MIN_WEEKS graded weeks).

Results come from box-score stats (player_game_stats), not platform totals.
A player counts as having played if he logged an offensive snap or a stat
line (a zero-catch receiver scores 0); players who did not play are excluded
for every source alike (conditional on playing, as the engine projects). Research only: nothing here
changes decisions, and serving_promoted stays False.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.models.facts import Game, PlayerGameStat, PlayerSnapCount
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from src.services.roster_stat_prospective import publish

POSITIONS = ("QB", "RB", "WR", "TE")
CAPTURE_WINDOW = timedelta(hours=3)
SNAPSHOT_MAX_AGE = timedelta(hours=2)
ALIAS = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}


def archive_root():
    from src.services.projection_engine_prospective import archive_root as engine_root
    return engine_root() / "pool"


def _numeric(stats: dict) -> dict:
    return {k: round(float(v), 4) for k, v in stats.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and not k.startswith(("pts_", "adp_"))}


async def _latest_projections(db, week: int):
    row = (await db.scalars(select(SleeperLeagueSnapshot).join(
        SleeperLeague, SleeperLeague.league_id == SleeperLeagueSnapshot.league_id).where(
        SleeperLeague.sport == "nfl", SleeperLeague.platform == "sleeper",
        SleeperLeagueSnapshot.kind == "projections", SleeperLeagueSnapshot.week == week).order_by(
        SleeperLeagueSnapshot.synced_at.desc()).limit(1))).first()
    return row if row and isinstance(row.payload, dict) else None


async def capture(db, *, now: datetime | None = None) -> dict:
    from src.services.projection_engine_prospective import latest_sleeper_catalog
    from src.services.team_model_serving import team_codes
    now = now or datetime.now(timezone.utc)
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None),
        Game.game_time > now + timedelta(minutes=5), Game.game_time <= now + CAPTURE_WINDOW))).all()
    if not games:
        return {"status": "no_games_in_window", "captured": 0}
    catalog, _ = await latest_sleeper_catalog(db)
    codes = await team_codes(db)
    written, skipped = 0, defaultdict(int)
    for week in sorted({g.week for g in games if g.week is not None}):
        snapshot = await _latest_projections(db, week)
        if snapshot is None or now - snapshot.synced_at > SNAPSHOT_MAX_AGE:
            skipped["no_current_projection_snapshot"] += 1
            continue
        team_game = {}
        for g in games:
            if g.week == week:
                for team in (g.home_team_id, g.away_team_id):
                    if codes.get(team):
                        team_game[ALIAS.get(codes[team], codes[team])] = g
        candidates = {}
        for sid, stats in snapshot.payload.items():
            info = catalog.get(sid) or {}
            team = info.get("team")
            game = team_game.get(ALIAS.get(team, team)) if team else None
            if info.get("position") not in POSITIONS or game is None or not isinstance(stats, dict):
                continue
            if not float(stats.get("gp") or 0):
                skipped["not_projected_to_play"] += 1
                continue
            candidates[sid] = (game, info["position"], team, _numeric(stats))
        resolved = await resolve_platform_players(db, "sleeper", sorted(candidates))
        for sid, (game, position, team, stats) in candidates.items():
            player = resolved.get(sid)
            if player is None:
                skipped["unresolved_player"] += 1
                continue
            rid = hashlib.sha256(f"sleeper_pool:{game.id}:{player.id}".encode()).hexdigest()
            written += bool(publish(archive_root() / "forecasts" / f"{rid}.json", {
                "id": rid, "source": "sleeper", "captured_at": now.isoformat(),
                "projection_synced_at": snapshot.synced_at.isoformat(), "game_id": str(game.id),
                "season": game.season, "week": week, "kickoff": game.game_time.isoformat(),
                "player_id": str(player.id), "sleeper_id": sid, "team": team, "position": position, "stats": stats,
                "serving_promoted": False}))
    return {"status": "captured", "games": len(games), "captured": written, "skipped": dict(skipped)}


def frozen(root=None) -> dict[tuple[str, str], dict]:
    root = root or archive_root()
    out = {}
    for path in sorted((root / "forecasts").glob("*.json")):
        r = json.loads(path.read_text())
        if datetime.fromisoformat(r["captured_at"]) < datetime.fromisoformat(r["kickoff"]):
            out[(r["game_id"], r["player_id"])] = r
    return out


def points(stats: dict, weights: dict) -> float:
    return sum(float(stats.get(k, 0.0)) * w for k, w in weights.items())


def pair_rows(sleeper: dict, challengers: dict[str, dict], actual: dict, leagues: list) -> dict[str, list[dict]]:
    """Rows for promotion_check, one list per challenger, each paired with Sleeper on rows every source covers.

    sleeper / challengers[name]: {(game_id, player_id): {"stats": ..., "position": ..., "week": ...,
    "keys": "sleeper" | "internal"}}; actual: {(game_id, player_id): internal stats}.
    """
    out = defaultdict(list)
    for league in leagues:
        weights = offensive_weights(league.scoring_settings)
        internal = {CORE[k]: w for k, w in weights.items() if k in CORE}
        for key, base in sleeper.items():
            result = actual.get(key)
            others = {name: rows.get(key) for name, rows in challengers.items()}
            if result is None or any(v is None for v in others.values()):
                continue
            truth = points(result, internal)
            s = points(base["stats"], weights)
            scored = {name: points(v["stats"], internal if v.get("keys") == "internal" else weights) for name, v in others.items()}
            scored["consensus"] = (s + sum(scored.values())) / (1 + len(scored))
            for name, value in scored.items():
                out[name].append({"league_id": league.league_id, "season": base.get("season"), "week": base["week"], "position": base["position"],
                                  "game_id": key[0], "player_id": key[1], "actual": round(truth, 2),
                                  "sleeper": round(s, 2), "engine": round(value, 2),
                                  "sleeper_error": abs(s - truth), "engine_error": abs(value - truth)})
    return out


async def report(db) -> dict:
    from src.services import espn_projections
    from src.services.projection_engine_prospective import (MIN_WEEKS, archive_root as engine_root,
                                                            promotion_check, summarize, version, evidence_breakdown)
    sleeper = frozen()
    current = version()
    engine = {}
    for path in sorted((engine_root() / "forecasts").glob("*.json")):
        r = json.loads(path.read_text())
        if r["version"] == current and datetime.fromisoformat(r["captured_at"]) < datetime.fromisoformat(r["kickoff"]):
            engine[(r["game_id"], r["player_id"])] = {**r, "keys": "internal"}
    espn = {k: {**v, "keys": "sleeper"} for k, v in espn_projections.frozen().items()}
    game_ids = {uuid.UUID(g) for g, _ in sleeper}
    final = {str(g.id) for g in (await db.scalars(select(Game).where(Game.id.in_(game_ids), Game.status == "final"))).all()} if game_ids else set()
    keys = [k for k in sleeper if k[0] in final]
    actual: dict = {}
    internal_names = set(CORE.values())
    if keys:
        rows = (await db.execute(select(PlayerGameStat.game_id, PlayerGameStat.player_id, PlayerGameStat.stat_type,
                                        PlayerGameStat.value).where(
            PlayerGameStat.game_id.in_({uuid.UUID(g) for g, _ in keys}),
            PlayerGameStat.player_id.in_({uuid.UUID(p) for _, p in keys})))).all()
        snaps = (await db.execute(select(PlayerSnapCount.game_id, PlayerSnapCount.player_id).where(
            PlayerSnapCount.game_id.in_({uuid.UUID(g) for g, _ in keys}), PlayerSnapCount.offense_snaps > 0))).all()
        wanted = set(keys)
        for gid, pid in snaps:
            if (k := (str(gid), str(pid))) in wanted:
                actual.setdefault(k, {})
        for gid, pid, stat, value in rows:
            if (k := (str(gid), str(pid))) in wanted:
                row = actual.setdefault(k, {})  # a stat line also means he played
                if stat in internal_names:
                    row[stat] = value
        # Snap counts arrive with nflverse's weekly release; a game without any snap row is not yet gradeable.
        snapped = {str(g) for g, _ in snaps}
        actual = {k: v for k, v in actual.items() if k[0] in snapped}
    leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.sport == "nfl",
                                                            SleeperLeague.platform == "sleeper"))).all()
    final_sleeper = {k: sleeper[k] for k in keys}
    tracks = {"engine_v1": pair_rows(final_sleeper, {"engine_v1": engine}, actual, leagues)["engine_v1"],
              "espn": pair_rows(final_sleeper, {"espn": espn}, actual, leagues)["espn"]}
    both = pair_rows(final_sleeper, {"espn": espn, "engine_v1": engine}, actual, leagues)
    tracks["consensus"] = both["consensus"]
    statuses = {"sleeper_frozen": len(sleeper), "final_games_rows": len(keys), "played": len(actual),
                "with_engine": sum(k in engine for k in keys), "with_espn": sum(k in espn for k in keys)}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "harness": "full_pool_box_score",
           "engine_version": current, "statuses": statuses,
           "tracks": {name: {"all_paired": summarize(rows), "promotion": promotion_check(rows, MIN_WEEKS),
                             **evidence_breakdown(rows), "evidence_type": "immutable_pregame_forecasts_current_version"}
                      for name, rows in tracks.items()},
           "status": "prospective_research", "serving_promoted": False}
    publish(archive_root() / "reports" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json", out)
    return out
