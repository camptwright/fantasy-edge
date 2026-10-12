"""Prospective capture and paired grading for projection engine v1.

Capture: every projection for a scheduled NFL game kicking off 5 minutes to
72 hours from now (the window fantasy_prospective uses) is frozen create-only
under raw/projection-engine/forecasts. The id binds version, game and player,
so the first observation wins and a rerun cannot replace it with hindsight.

Grading: each frozen engine forecast is paired with the frozen Sleeper
provider-weekly projection for the same player and game, scored with that
league's current settings only if they still hash to the scoring the Sleeper
record was captured under. Both are graded by fantasy_weekly_evidence.grade
against the platform's final league-scored points.

Promotion criterion (reported, never applied): for the CURRENT version only,
at least MIN_WEEKS independent graded weeks, the starter-pool paired MAE
difference's week-bootstrap 95% interval entirely below zero, and no
position's interval entirely above zero. `serving_promoted` stays False
regardless; replacing Sleeper in serving is a separate owner decision.
"""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select

from config.settings import get_settings
from src.models.facts import Game
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.fantasy_weekly_evidence import grade
from src.services.player_identity import resolve_platform_players
from src.services.projection_engine import RECIPE, project, score
from src.services.roster_stat_prospective import publish

MIN_WEEKS = 6
SOURCES = ("projection_engine.py", "game_environment.py")


def version() -> str:
    """Semantic identity: the engine's parsed source (comments ignored) and numpy."""
    root = Path(__file__).resolve().parent
    parts = [ast.dump(ast.parse((root / name).read_text())) for name in SOURCES]
    parts.append(f"numpy={np.__version__}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def provider_scoring_hash(scoring: dict) -> str:
    """The exact formula fantasy_weekly_evidence.candidates freezes with."""
    return hashlib.sha256(json.dumps(scoring, sort_keys=True).encode()).hexdigest()


def archive_root() -> Path:
    return Path(get_settings().raw_archive_dir) / "projection-engine"


def depth_version() -> str:
    """Identity of the depth/status variant: v1's sources plus the adjustment."""
    root = Path(__file__).resolve().parent
    return hashlib.sha256((version() + ast.dump(ast.parse((root / "projection_depth.py").read_text())))
                          .encode()).hexdigest()


VARIANTS = {"v1": ("forecasts", "reports"), "depth": ("depth/forecasts", "depth/reports")}


def _record(p, game, recipe: str, v: str, now: datetime, extra: dict | None = None) -> dict:
    return {"id": hashlib.sha256(f"{v}:{p.game_id}:{p.player_id}".encode()).hexdigest(),
            "recipe": recipe, "version": v, "captured_at": now.isoformat(),
            "game_id": str(p.game_id), "season": game.season, "week": game.week,
            "kickoff": game.game_time.isoformat(), "player_id": str(p.player_id),
            "team_id": str(p.team_id), "position": p.position,
            "stats": {k: round(val, 4) for k, val in p.stats.items()},
            "team_pass_attempts": round(p.team_pass_attempts, 3),
            "team_carries": round(p.team_carries, 3), "implied_points": round(p.implied_points, 3),
            "games_used": p.games_used, "conditional_on_playing": True, "serving_promoted": False,
            **(extra or {})}


async def latest_sleeper_catalog(db) -> tuple[dict, datetime | None]:
    """Newest Sleeper (not ESPN) player catalog snapshot, with its sync time."""
    row = (await db.scalars(select(SleeperLeagueSnapshot).join(
        SleeperLeague, SleeperLeague.league_id == SleeperLeagueSnapshot.league_id).where(
        SleeperLeague.sport == "nfl", SleeperLeague.platform == "sleeper",
        SleeperLeagueSnapshot.kind == "player_metadata").order_by(
        SleeperLeagueSnapshot.synced_at.desc()).limit(1))).first()
    return (row.payload if row and isinstance(row.payload, dict) else {}), (row.synced_at if row else None)


async def capture(db, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None),
        Game.game_time > now + timedelta(minutes=5),
        Game.game_time <= now + timedelta(hours=72)))).all()
    if not games:
        return {"status": "no_games_in_window", "captured": 0}
    v = version()
    by_id = {g.id: g for g in games}
    projections = await project(db, list(games), now)
    written = 0
    for p in projections.values():
        record = _record(p, by_id[p.game_id], RECIPE, v, now)
        written += bool(publish(archive_root() / "forecasts" / f"{record['id']}.json", record))
    out = {"status": "captured", "version": v, "games": len(games),
           "projected": len(projections), "captured": written}
    # Depth/status variant (E3 amendment): only with a catalog that carries
    # depth fields and is at most two days old; otherwise not captured.
    catalog, synced_at = await latest_sleeper_catalog(db)
    has_depth = any(isinstance(i, dict) and "depth_chart_order" in i for i in catalog.values())
    if not has_depth or synced_at is None or now - synced_at > timedelta(days=2):
        out["depth"] = {"status": "no_current_depth_catalog", "captured": 0}
        return out
    from src.services import projection_depth
    depth = await projection_depth.depth_inputs(db, catalog)
    adjusted, removed = await projection_depth.project(db, list(games), now, depth)
    dv, depth_written = depth_version(), 0
    for p in adjusted.values():
        d = depth.get(p.player_id)
        record = _record(p, by_id[p.game_id], projection_depth.RECIPE, dv, now, {
            "depth_catalog_synced_at": synced_at.isoformat(),
            "depth_input": None if d is None else {
                "status": d.status, "injury_status": d.injury_status,
                "depth_chart_position": d.depth_position, "depth_chart_order": d.depth_order}})
        depth_written += bool(publish(archive_root() / "depth" / "forecasts" / f"{record['id']}.json", record))
    out["depth"] = {"status": "captured", "version": dv, "projected": len(adjusted),
                    "removed": len(removed), "captured": depth_written}
    return out


def week_bootstrap_ci(diffs_by_week: dict[int, list[float]], draws: int = 4000, seed: int = 7):
    if len(diffs_by_week) < 2:
        return None
    rng = np.random.default_rng(seed)
    weeks = list(diffs_by_week)
    means = []
    for _ in range(draws):
        sample = np.concatenate([diffs_by_week[w] for w in rng.choice(weeks, size=len(weeks))])
        means.append(sample.mean())
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "weeks": [], "ci": None}
    diffs: dict[int, list[float]] = {}
    for r in rows:
        diffs.setdefault(r["week"], []).append(r["engine_error"] - r["sleeper_error"])
    return {"n": len(rows), "weeks": sorted(diffs),
            "engine_mae": round(float(np.mean([r["engine_error"] for r in rows])), 3),
            "sleeper_mae": round(float(np.mean([r["sleeper_error"] for r in rows])), 3),
            "engine_bias": round(float(np.mean([r["engine"] - r["actual"] for r in rows])), 3),
            "sleeper_bias": round(float(np.mean([r["sleeper"] - r["actual"] for r in rows])), 3),
            "paired_difference": round(float(np.mean([r["engine_error"] - r["sleeper_error"] for r in rows])), 3),
            "ci": week_bootstrap_ci(diffs)}


POOL = {"QB": 12, "RB": 24, "WR": 30, "TE": 12}


def starter_pool(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["league_id"], r["week"], r["position"]), []).append(r)
    selected = []
    for (_, _, position), members in groups.items():
        n = POOL.get(position, 0)
        keep = {id(r) for r in sorted(members, key=lambda r: -r["sleeper"])[:n]}
        keep |= {id(r) for r in sorted(members, key=lambda r: -r["actual"])[:n]}
        selected.extend(r for r in members if id(r) in keep)
    return selected


def promotion_check(rows: list[dict]) -> dict:
    pool = starter_pool(rows)
    overall = summarize(pool)
    positions = {p: summarize([r for r in pool if r["position"] == p]) for p in POOL}
    blockers = []
    if len(overall["weeks"]) < MIN_WEEKS:
        blockers.append(f"needs_{MIN_WEEKS}_graded_weeks_has_{len(overall['weeks'])}")
    if overall["ci"] is None or overall["ci"][1] >= 0:
        blockers.append("pool_improvement_not_established")
    worse = [p for p, s in positions.items() if s["ci"] and s["ci"][0] > 0]
    if worse:
        blockers.append("worse_than_sleeper:" + ",".join(worse))
    return {"eligible_for_owner_review": not blockers, "blockers": blockers,
            "pool": overall, "positions": positions, "serving_promoted": False}


async def report(db, variant: str = "v1") -> dict:
    root = archive_root()
    forecasts_dir, reports_dir = VARIANTS[variant]
    current = version() if variant == "v1" else depth_version()
    engine = [json.loads(p.read_text()) for p in sorted((root / forecasts_dir).glob("*.json"))]
    engine = {(r["game_id"], r["player_id"]): r for r in engine if r["version"] == current}
    provider_dir = Path(get_settings().raw_archive_dir) / "fantasy-prospective" / "provider-weekly"
    sleeper = [json.loads(p.read_text()) for p in sorted(provider_dir.glob("*.json"))]
    engine_games = {game_id for game_id, _ in engine}
    sleeper = [r for r in sleeper if not r["league_id"].startswith("espn:")
               and r.get("prediction", {}).get("source") == "sleeper"
               and r["game_id"] in engine_games]
    identity = await resolve_platform_players(db, "sleeper", sorted({r["player_id"] for r in sleeper}))
    leagues = {lg.league_id: lg for lg in (await db.scalars(select(SleeperLeague))).all()}
    rows, statuses = [], {}

    def count(status):
        statuses[status] = statuses.get(status, 0) + 1

    for r in sleeper:
        player = identity.get(r["player_id"])
        frozen = engine.get((r["game_id"], str(player.id))) if player else None
        league = leagues.get(r["league_id"])
        if frozen is None or league is None:
            count("unpaired")
            continue
        if datetime.fromisoformat(frozen["captured_at"]) >= datetime.fromisoformat(frozen["kickoff"]):
            count("invalid_engine_capture_time")
            continue
        if r.get("scoring_hash") != provider_scoring_hash(league.scoring_settings):
            count("scoring_changed_since_capture")
            continue
        game = await db.get(Game, uuid.UUID(r["game_id"]))
        snapshot = await db.get(SleeperLeagueSnapshot, (r["league_id"], r["week"], "matchups"))
        result = grade(r, game, snapshot)
        if result["status"] != "graded_platform_total":
            count(result["status"])
            continue
        weights = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
        points = score(frozen["stats"], weights)
        count("graded")
        rows.append({"league_id": r["league_id"], "week": r["week"], "position": r["position"],
                     "actual": result["actual"], "sleeper": r["prediction"]["points"],
                     "engine": round(points, 2), "sleeper_error": result["absolute_error"],
                     "engine_error": abs(points - result["actual"])})
    from src.services.fantasy_outcomes import load_model
    model = load_model() or {}
    weights = model.get("candidate_blend_weights", {})
    blended = [{**r, "engine": round(w * r["engine"] + (1 - w) * r["sleeper"], 2),
                "engine_error": abs(w * r["engine"] + (1 - w) * r["sleeper"] - r["actual"])}
               for r in rows if (w := weights.get(r["position"])) is not None]
    # Only weeks after the weights were fitted are prospective for the blend.
    fitted = model.get("fitted_at")
    fitted_week = max(model.get("fit_data", {}).get("paired_weeks", [0]) or [0])
    out_blend = {"weights": weights, "fitted_at": fitted,
                 "prospective_weeks_after": fitted_week,
                 "all_paired": summarize([r for r in blended if r["week"] > fitted_week]),
                 "promotion": promotion_check([r for r in blended if r["week"] > fitted_week])}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "variant": variant,
           "candidate_blend": out_blend,
           "recipe": RECIPE if variant == "v1" else RECIPE + "_depth", "version": current, "engine_forecasts": len(engine), "statuses": statuses,
           "all_paired": summarize(rows), "promotion": promotion_check(rows),
           "status": "prospective_research", "serving_promoted": False}
    publish(root / reports_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json", out)
    return out
