"""Which team each NBA player played for in each game, from archived ESPN box scores.

PlayerGameStat has no team, and NBA players move mid-season, so the prop
board's opponent hit rates and D-vs-Pos need the team per player-game. Each
final game's ResultSyncState (provider espn_nba) names its archived ESPN
summary (src/ingest/result_repair.py); `boxscore.players[]` gives the team's
ESPN id, its athletes and who started, and `pickcenter[0]` the pregame
DraftKings total and spread (verified 2026-10-20 on 1,316 2025-26 games;
`details` "OKC -9.5" names the favourite). Read incrementally into
DerivedCheckpoint `nba_player_teams`: {game_id: {players: {player_id:
team_id}, starters, total, home_spread}}. A game whose archive is missing or
unreadable is left out (missing, not guessed).
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.models.governance import DerivedCheckpoint, ResultSyncState
from src.models.identity import PlayerExternalId, Team
from src.services.forecast_evidence import digest

NAME = "nba_player_teams"
PROVIDER = "espn_nba"
VERSION = 2


def read(path: str) -> dict | None:
    for candidate in (Path(path), Path(path + ".gz")):
        try:
            if candidate.suffix == ".gz":
                return json.loads(gzip.decompress(candidate.read_bytes()))
            return json.loads(candidate.read_text())
        except (OSError, ValueError):
            continue
    return None


def teams_in(payload: dict) -> dict[str, str]:
    """{ESPN athlete id: ESPN team id} for athletes who played."""
    return {a: t for a, (t, _) in athletes(payload).items()}


def athletes(payload: dict) -> dict[str, tuple[str, bool]]:
    """{ESPN athlete id: (ESPN team id, started)} for athletes who played."""
    out = {}
    for team in (payload.get("boxscore") or {}).get("players") or []:
        team_id = str((team.get("team") or {}).get("id") or "")
        for block in team.get("statistics") or []:
            for row in block.get("athletes") or []:
                athlete = str((row.get("athlete") or {}).get("id") or "")
                if team_id and athlete and row.get("didNotPlay") is False:
                    out[athlete] = (team_id, row.get("starter") is True)
    return out


def market(payload: dict) -> tuple[float | None, float | None]:
    """(pregame total, home spread; negative = home favoured) from ESPN pickcenter, else (None, None)."""
    pick = (payload.get("pickcenter") or [None])[0] or {}
    total = pick.get("overUnder")
    home = next((str((t.get("team") or {}).get("abbreviation") or "") for t in (payload.get("boxscore") or {}).get("teams") or []
                 if t.get("homeAway") == "home"), "")
    spread = None
    favourite, _, number = str(pick.get("details") or "").partition(" ")
    if favourite.upper() in ("EVEN", "PK"):
        spread = 0.0
    else:
        try:
            size = abs(float(number))
            spread = -size if favourite == home else size if favourite and home else None
        except ValueError:
            spread = None
    return (float(total) if isinstance(total, (int, float)) else None), spread


async def player_teams(db, *, now: datetime | None = None) -> dict[str, dict[str, str]]:
    now = now or datetime.now(timezone.utc)
    row = await db.get(DerivedCheckpoint, NAME)
    cached = dict((row.payload or {}).get("games", {})) if row and (row.payload or {}).get("version") == VERSION else {}
    states = (await db.scalars(select(ResultSyncState).where(ResultSyncState.provider == PROVIDER))).all()
    pending = [s for s in states if str(s.game_id) not in cached]
    if not pending:
        return cached
    players = {e.external_id: str(e.player_id) for e in (await db.scalars(
        select(PlayerExternalId).where(PlayerExternalId.source == PROVIDER))).all()}
    teams = {t.espn_id: str(t.id) for t in (await db.scalars(select(Team).where(Team.sport == "nba"))).all()}
    for state in pending:
        try:
            path = json.loads(state.detail or "{}").get("evidence_archive")
        except ValueError:
            path = None
        payload = read(path) if path else None
        if payload is None:
            continue
        box = payload.get("payload") or {}
        seen = {players[a]: (teams[t], started) for a, (t, started) in athletes(box).items() if a in players and t in teams}
        if seen:
            total, spread = market(box)
            cached[str(state.game_id)] = {"players": {p: t for p, (t, _) in seen.items()},
                                          "starters": sorted(p for p, (_, s) in seen.items() if s),
                                          "total": total, "home_spread": spread}
    body = {"version": VERSION, "generated_at": now.isoformat(), "games": cached}
    values = {"name": NAME, "digest": digest(body), "payload": body, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    return cached
