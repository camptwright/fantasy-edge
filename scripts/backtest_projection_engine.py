"""Retrospective paired backtest: projection engine v1 vs frozen Sleeper projections.

Run in the worker environment (needs the DB and the raw archive):
    python -m scripts.backtest_projection_engine [--season 2026]

For every frozen pre-kickoff Sleeper projection in raw/fantasy-prospective/
provider-weekly, the engine projects the same player-week using only games
that kicked off before that week's earliest Sleeper capture and lines
observed by then, scored with the same league's scoring settings. Both are
graded by the existing `fantasy_weekly_evidence.grade` against the
platform's own final league-scored points, so the answer key is identical.

Accuracy method follows FantasyPros' published in-season methodology:
absolute error against actual points, evaluated on a pool of each
position's top-N by projection or by actual result per league-week, plus
the full paired set. Weeks are the independent unit (one NFL slate), so
the paired-difference interval is a week-clustered bootstrap.

This is retrospective research: stats are read as stored today (including
later corrections), and the engine's hyperparameters were not tuned on
these weeks but were also not frozen before them. It cannot promote
anything; prospective capture is the qualification path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.fantasy_weekly_evidence import grade
from src.services.player_identity import resolve_platform_players
from src.services.projection_engine import RECIPE, project, score
from src.services.projection_engine_prospective import promotion_check, starter_pool, summarize

async def run(season: int) -> dict:
    root = Path(get_settings().raw_archive_dir) / "fantasy-prospective" / "provider-weekly"
    records = [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))]
    records = [r for r in records if not r["league_id"].startswith("espn:")
               and r.get("prediction", {}).get("source") == "sleeper"]
    async with get_worker_db() as db:
        leagues = {lg.league_id: lg for lg in (await db.scalars(select(SleeperLeague))).all()}
        games = {g.id: g for g in (await db.scalars(select(Game).where(
            Game.id.in_({uuid.UUID(r["game_id"]) for r in records})))).all()}
        records = [r for r in records if (g := games.get(uuid.UUID(r["game_id"]))) and g.season == season]
        identity = await resolve_platform_players(db, "sleeper", sorted({r["player_id"] for r in records}))

        by_week: dict[int, list[dict]] = defaultdict(list)
        for r in records:
            by_week[r["week"]].append(r)
        rows, blocked = [], defaultdict(int)
        for week, week_records in sorted(by_week.items()):
            cutoff = min(datetime.fromisoformat(r["captured_at"]) for r in week_records)
            target = (await db.scalars(select(Game).where(Game.sport == "nfl", Game.season == season,
                                                          Game.week == week))).all()
            projections = await project(db, list(target), cutoff)
            for r in week_records:
                league = leagues.get(r["league_id"])
                player = identity.get(r["player_id"])
                proj = projections.get(player.id) if player else None
                if league is None:
                    blocked["unknown_league"] += 1
                    continue
                if proj is None:
                    blocked["no_engine_projection" if player else "unresolved_identity"] += 1
                    continue
                weights = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
                engine_points = score(proj.stats, weights)
                snapshot = await db.get(SleeperLeagueSnapshot, (r["league_id"], week, "matchups"))
                game = games[uuid.UUID(r["game_id"])]
                sleeper_grade = grade(r, game, snapshot)
                if sleeper_grade["status"] != "graded_platform_total":
                    blocked[sleeper_grade["status"]] += 1
                    continue
                actual = sleeper_grade["actual"]
                rows.append({"league_id": r["league_id"], "week": week, "position": r["position"],
                             "player_id": r["player_id"], "actual": actual,
                             "sleeper": r["prediction"]["points"], "engine": round(engine_points, 2),
                             "sleeper_error": sleeper_grade["absolute_error"],
                             "engine_error": abs(engine_points - actual),
                             "unmodeled_scoring_keys": sorted(set(offensive_weights(league.scoring_settings)) - set(CORE))})
    positions = sorted({r["position"] for r in rows})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "recipe": RECIPE, "season": season,
        "status": "retrospective_research", "serving_promoted": False,
        "records_considered": len(records), "blocked": dict(blocked),
        "all_paired": summarize(rows), "pool": summarize(starter_pool(rows)),
        "by_position": {p: {"all": summarize([r for r in rows if r["position"] == p]),
                            "pool": summarize([r for r in starter_pool(rows) if r["position"] == p])}
                        for p in positions},
        "criterion_if_this_were_prospective": promotion_check(rows),
        "unmodeled_scoring_keys_by_league": {r["league_id"]: r["unmodeled_scoring_keys"] for r in rows},
        "scope": "Retrospective; stats as stored today. Engine vs frozen pre-kickoff Sleeper "
                 "projections, both graded on platform final points. Not a promotion test.",
    }
    out = Path(get_settings().raw_archive_dir) / "projection-engine" / "backtests"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{season}.json"
    path.write_text(json.dumps({**report, "rows": rows}, indent=1))
    return {**report, "archive": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.season)), indent=1))


if __name__ == "__main__":
    main()
