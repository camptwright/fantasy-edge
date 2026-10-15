"""Prospective capture of projection engine v2 (lean), beside v1 and the depth variant.

v2 failed its registered 2022 test (docs/2026-10-15-engine-v2-plan.md), so
it is research only: frozen before kickoff, graded against Sleeper frozen
before kickoff by projection_engine_prospective.report(db, "v2"), never
served. Inputs come from nflverse release CSVs and Sleeper's archive
(projection_engine_v2_data.load_release) so the lab and this capture run the
same feature code; lines come from this app's own market snapshots, as for v1.

Candidates per team: players nflverse's weekly roster lists as active or
inactive for the target week (latest roster week otherwise), at QB/RB/WR/TE.
Projections are conditional on playing, like v1's.
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select

from config.settings import get_settings
from src.models.facts import Game
from src.models.identity import Player, Team
from src.services import projection_engine_v2 as v2
from src.services import projection_engine_v2_data as D
from src.services.game_environment import environments
from src.services.projection_engine_prospective import archive_root
from src.services.roster_stat_prospective import publish

RECIPE = "projection_engine_v2_lean"
SOURCES = ("projection_engine_v2.py", "projection_engine_v2_data.py", "projection_engine_v2_prospective.py",
           "game_environment.py")
WINDOW = timedelta(hours=72)


def version() -> str:
    """Semantic identity: parsed sources (comments ignored), the feature groups and numpy."""
    root = Path(__file__).resolve().parent
    parts = [ast.dump(ast.parse((root / name).read_text())) for name in SOURCES]
    parts += [f"groups={','.join(D.LEAN)}", f"numpy={np.__version__}"]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def cache_dir() -> Path:
    return Path(get_settings().raw_archive_dir) / "nflverse-v2-cache"


def candidates(data: dict, season: int, week: int, team: str) -> list[tuple[str, str]]:
    """(gsis, position) on the team's weekly roster for this week, or its latest earlier roster week."""
    weeks = sorted({w for (s, w, _), (t, _, _) in data["roster_status"].items() if s == season and t == team and w <= week})
    if not weeks:
        return []
    w = weeks[-1]
    return sorted({(g, pos) for (s, wk, g), (t, status, pos) in data["roster_status"].items()
                   if s == season and wk == w and t == team and status in D.ON_ROSTER and pos in v2.POSITIONS})


async def capture(db, *, now: datetime | None = None, loaded: tuple | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None),
        Game.game_time > now + timedelta(minutes=5), Game.game_time <= now + WINDOW))).all()
    if not games:
        return {"status": "no_games_in_window", "captured": 0}
    season = max(g.season for g in games)
    data, extra = loaded or D.load_release(cache_dir(), season)
    abbr = dict((await db.execute(select(Team.id, Team.nflverse_abbr).where(Team.sport == "nfl"))).all())
    env = await environments(db, [g.id for g in games], as_of=now)
    nflverse = {(g["season"], g["week"], g["home"], g["away"]): gid for gid, g in data["games"].items()}
    targets, unmatched = [], []
    for g in games:
        home, away = abbr.get(g.home_team_id), abbr.get(g.away_team_id)
        gid = nflverse.get((g.season, g.week, home, away))
        e = env.get(g.id)
        if gid is None or e is None:
            unmatched.append({"game_id": str(g.id), "reason": "no_nflverse_game" if gid is None else "no_line"})
            continue
        for team, opp, is_home in ((home, away, True), (away, home, False)):
            for gsis, pos in candidates(data, g.season, g.week, team):
                targets.append({"db_game": g, "db_team": g.home_team_id if is_home else g.away_team_id,
                                "game_id": gid, "season": g.season, "week": g.week, "kickoff": g.game_time,
                                "team": team, "opp": opp, "gsis": gsis, "position": pos,
                                "implied": e.home_points if is_home else e.away_points,
                                "spread": e.home_spread if is_home else -e.home_spread,
                                "total": e.home_points + e.away_points})
    if not targets:
        return {"status": "no_candidates", "captured": 0, "unmatched": unmatched}
    team_rows, pairs = D.iter_features(data, extra)
    team_rows = [t for t in team_rows if t["kickoff"] < now]
    tf = v2.Frame.from_rows(team_rows, list(v2.TEAM_FEATURES) + ["t_tpa"])
    team_y = {k: np.array([t[k] for t in team_rows], float) for k in ("pass_att", "carries")}
    _, target_rows = D.target_rows(data, extra, targets)
    trained = [0]

    def rows():
        for r, m in pairs:
            if m["kickoff"] < now:
                trained[0] += 1
                yield r
        yield from target_rows
    frame = v2.frame_from_iter(rows(), v2.row_names())
    train = np.arange(len(frame.X)) < trained[0]
    model = v2.fit(tf, team_y, np.ones(len(team_rows), bool), frame, train, D.LEAN)
    stats = v2.predict(model, frame, ~train)
    ids = dict((await db.execute(select(Player.gsis_id, Player.id).where(
        Player.gsis_id.in_({t["gsis"] for t in targets})))).all())
    tvol = model.team["pass_att"].predict(frame, ~train), model.team["carries"].predict(frame, ~train)
    v, root, written, missing = version(), archive_root() / "v2" / "forecasts", 0, 0
    for i, t in enumerate(targets):
        player = ids.get(t["gsis"])
        if player is None:
            missing += 1
            continue
        g = t["db_game"]
        record = {"id": hashlib.sha256(f"{v}:{g.id}:{player}".encode()).hexdigest(),
                  "recipe": RECIPE, "version": v, "captured_at": now.isoformat(),
                  "game_id": str(g.id), "season": g.season, "week": g.week, "kickoff": g.game_time.isoformat(),
                  "player_id": str(player), "team_id": str(t["db_team"]), "position": t["position"],
                  "gsis_id": t["gsis"], "stats": {s: round(float(x), 4) for s, x in zip(v2.STATS, stats[i])},
                  "team_pass_attempts": round(float(tvol[0][i]), 3), "team_carries": round(float(tvol[1][i]), 3),
                  "implied_points": round(float(t["implied"]), 3), "groups": list(D.LEAN),
                  "conditional_on_playing": True, "serving_promoted": False}
        written += bool(publish(root / f"{record['id']}.json", record))
    return {"status": "captured", "version": v, "games": len(games), "candidates": len(targets),
            "captured": written, "no_player_identity": missing, "unmatched": unmatched,
            "training_rows": trained[0], "serving_promoted": False}
