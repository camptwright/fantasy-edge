"""How often players with a designation actually play: P(plays | status, practice, position).

Fitted by scripts/research_availability.py on nflverse injury reports joined
to PFR snap counts (regulars only: >= 40% of offensive snaps over the previous
three games), 2016-2023, scored on 2024-2025: Brier 0.104 against 0.164 for
the rule lineups use (Questionable plays, Doubtful does not). Regular
Questionable players played 68% of the time in 2024-2025; with a full Friday
practice ~90%, limited ~75%, no practice ~50%.

Live inputs: the platform's designation (Sleeper/ESPN injury_status) and the
same week's practice participation from nflverse's current-season injury
report (official team reports, refreshed every REFRESH). Display and the
risk-adjusted Start/Sit figure only; lineup and waiver decisions, and the
versioned prediction, are unchanged.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy.dialects.postgresql import insert

from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest
from src.services.availability_status import normalize_status, normalize_team

ARTIFACT = Path(__file__).resolve().parents[2] / "config" / "availability_rates.json"
URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
REFRESH = timedelta(hours=3)
PRACTICE = {"Did Not Participate In Practice": "dnp", "Limited Participation in Practice": "limited",
            "Full Participation in Practice": "full"}
PRACTICE_LABEL = {"dnp": "did not practice", "limited": "limited practice", "full": "full practice"}
DESIGNATIONS = {"QUESTIONABLE": "Questionable", "Q": "Questionable", "DOUBTFUL": "Doubtful", "D": "Doubtful"}


def name(season: int) -> str:
    return f"nflverse_injuries:{season}"


@lru_cache(maxsize=1)
def load() -> dict | None:
    return json.loads(ARTIFACT.read_text()) if ARTIFACT.exists() else None


def probability(status: str | None, practice: str | None, position: str | None, artifact: dict | None = None) -> dict | None:
    """{probability, n, basis} for a Questionable/Doubtful skill player; None when not designated or not modelled."""
    artifact = artifact or load()
    designation = DESIGNATIONS.get(normalize_status(status))
    if artifact is None or designation is None or position not in ("QB", "RB", "WR", "TE"):
        return None
    tables, k = artifact["tables"], artifact["shrink"]

    def cell(table, *key):
        c = tables[table].get("|".join(key))
        return (c["played"], c["n"]) if c else (0, 0)

    played, n = cell("status", designation)
    if not n:
        return None
    prior, basis, total = played / n, f"{designation}", n
    if practice in PRACTICE_LABEL:
        p, m = cell("status_practice", designation, practice)
        if m:
            prior = (p + k * prior) / (m + k)
            basis, total = f"{designation}, {PRACTICE_LABEL[practice]}", m
        p, m = cell("status_practice_position", designation, practice, position)
    else:
        p, m = 0, 0
    value = (p + k * prior) / (m + k) if m else prior
    return {"probability": round(value, 3), "n": m or total, "basis": f"{basis}, {position}" if m else basis}


def parse(text: str) -> dict[str, dict]:
    """gsis id -> latest-week report row {week, team, report_status, practice}."""
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        gsis, week = r.get("gsis_id"), r.get("week")
        if not gsis or not str(week).isdigit() or r.get("game_type") not in (None, "", "REG"):
            continue
        season = r.get('season')
        if not str(season).isdigit():
            continue
        row = {"season": int(season), "week": int(week), "team": r.get("team"), "report_status": r.get("report_status") or None,
               "practice": PRACTICE.get((r.get("practice_status") or "").strip()),
               "injury": r.get("report_primary_injury") or r.get("practice_primary_injury") or None,
               "reported_at": r.get('date_modified') or r.get('report_date') or r.get('practice_date') or r.get('date') or None}
        if gsis not in out or (row['season'], row["week"], row['reported_at'] or '') >= (out[gsis]['season'], out[gsis]["week"], out[gsis]['reported_at'] or ''):
            out[gsis] = row
    return out


async def latest(db, season: int) -> dict | None:
    row = await db.get(DerivedCheckpoint, name(season))
    return row.payload if row else None


async def refresh(db, *, now: datetime | None = None, fetcher=None) -> dict:
    now = now or datetime.now(timezone.utc)
    season = now.year if now.month >= 3 else now.year - 1
    previous = await latest(db, season)
    if previous and now - datetime.fromisoformat(previous["fetched_at"]) < REFRESH:
        return {"status": "fresh", "players": len(previous["players"])}
    try:
        if fetcher is None:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(URL.format(season=season))
                r.raise_for_status()
                text = r.text
        else:
            text = await fetcher(season)
        players = parse(text)
    except (httpx.HTTPError, csv.Error, ValueError) as exc:
        return {"status": "unavailable", "error": type(exc).__name__}
    payload = {"season": season, "fetched_at": now.isoformat(), "players": players}
    values = {"name": name(season), "digest": digest(payload), "payload": payload, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    return {"status": "refreshed", "players": len(players)}


async def attach(db, platform: str, data: dict | None, *, now: datetime | None = None) -> None:
    """p['_play'] = {probability, n, basis, practice} for designated skill players in the overview data."""
    if not data or load() is None:
        return
    designated = [p for p in data.get("players", [])
                  if DESIGNATIONS.get(normalize_status(p.get("injury_status")))]
    if not designated:
        return
    from src.services.player_identity import resolve_platform_players
    now = now or datetime.now(timezone.utc)
    season = now.year if now.month >= 3 else now.year - 1
    report = await latest(db, season) or {}
    week = data.get("week")
    resolved = await resolve_platform_players(db, platform, sorted({str(p["player_id"]) for p in designated}))
    for p in designated:
        player = resolved.get(str(p["player_id"]))
        row = report.get('players', {}).get(player.gsis_id) if player is not None and player.gsis_id else None
        evidence = practice_evidence(row, report, season=data.get('season', season), week=week,
                                     team=p.get('team'), now=now)
        practice = row.get('practice') if evidence['status'] == 'matched_fresh_report' else None
        result = probability(p.get("injury_status"), practice, p.get("position"))
        if result:
            p["_play"] = {**result, "practice": practice,
                'practice_evidence_status': evidence['status'], 'observed_at': evidence.get('reported_at'),
                'evidence': evidence}


def parsed_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


def practice_evidence(row, report, *, season, week, team, now):
    """Fetching an old file today cannot make an undated practice report current."""
    evidence = {'status': 'not_collected', 'source': 'nflverse_injury_reports',
                'fetched_at': report.get('fetched_at'), 'reported_at': (row or {}).get('reported_at')}
    if not row:
        return evidence
    evidence.update({'season': row.get('season'), 'week': row.get('week'), 'team': row.get('team')})
    if report.get('season') != season or row.get('season') != season or week is None or row.get('week') != week:
        evidence['status'] = 'season_or_week_mismatch'
    elif not normalize_team(team) or normalize_team(row.get('team')) != normalize_team(team):
        evidence['status'] = 'team_mismatch'
    else:
        fetched, reported = parsed_time(report.get('fetched_at')), parsed_time(row.get('reported_at'))
        if fetched is None or reported is None:
            evidence['status'] = 'undated_report'
        elif not timedelta(0) <= now-fetched <= timedelta(hours=6) or not timedelta(0) <= now-reported <= timedelta(days=4):
            evidence['status'] = 'stale_or_future_report'
        else:
            evidence['status'] = 'matched_fresh_report'
    return evidence
