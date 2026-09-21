"""Minimal production API for the restored NFL ingestion service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections import Counter

import httpx
import json
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.api.performance import PerformanceMiddleware, snapshot as performance_snapshot
from src.api.routers.sportsbook import router as sportsbook_router
from src.api.routers.nfl_predictor import router as nfl_predictor_router
from src.api.routers.ledger import router as ledger_router
import src.api.routers.ledger_imports  # noqa: F401 - registers receipt routes
from src.data.news import fetch_rss_headlines
from src.db.client import dispose_api_engine, get_api_engine
from src.db.client import get_db
from src.ingest.sleeper import sync_sleeper_account
from src.ingest.espn_fantasy import sync_espn_fantasy_account
from src.services.custom_projection import exact_projected_points as custom_projected_points, load_exact_2025_averages
from src.services.trade import evaluate_trade, suggest_trades
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster

bearer = HTTPBearer(auto_error=False)


def projection_rows(payload: object) -> list[dict]:
    """Sleeper returns projections as either a list of per-player dicts or
    an ID-keyed object - but confirmed live 2026-09-09, the ID-keyed shape
    (what /projections/nfl/... actually returns) never repeats the id
    inside its value, and each value is a FLAT stat dict
    ({"pts_ppr": 11.9, "rec_yd": 56.1, ...}), not a wrapper carrying its
    own "player_id"/"player"/"stats" sub-keys. The old version called
    payload.values() and then filtered for item.get("player_id"), which
    is always None on this shape - every row was silently dropped
    regardless of how much real data Sleeper returned. Both shapes are
    normalized to a uniform {"player_id": ..., "stats": {...}} row here."""
    if isinstance(payload, dict):
        return [
            {"player_id": str(player_id), "stats": stats}
            for player_id, stats in payload.items()
            if isinstance(stats, dict) and stats
        ]
    if isinstance(payload, list):
        return [
            {"player_id": str(item["player_id"]), "stats": item.get("stats", item)}
            for item in payload
            if isinstance(item, dict) and item.get("player_id")
        ]
    return []


# Confirmed live 2026-09-09: pure surname matching produced a real false
# positive - "Daniel Jones" matched a headline about Jerry Jones (the
# Cowboys owner, not a player) purely because "Jones" is a common NFL
# surname. Any surname this common (or generic English word - a few NFL
# surnames double as ordinary words too) is excluded from the
# surname-only fallback below rather than trying to disambiguate context
# a substring match cannot see.
_COMMON_SURNAMES_EXCLUDED_FROM_FALLBACK = {
    "jones", "smith", "johnson", "williams", "brown", "davis", "miller",
    "wilson", "moore", "taylor", "anderson", "thomas", "jackson", "white",
    "harris", "martin", "thompson", "robinson", "walker", "young", "allen",
    "king", "wright", "scott", "green", "baker", "hill", "adams", "campbell",
}


def match_player_news(name: str, headlines: list[dict]) -> list[dict]:
    """Deterministic, case-insensitive name matching against headline
    titles - not the model's job: confirmed live 2026-09-09 that asking
    the local fast model to do this same matching itself hallucinated the
    same one headline onto every single player regardless of whether
    their name actually appeared in it.

    Tries a full "first last" substring match first (low false-positive
    rate). Falls back to surname-only only when the surname is at least
    5 characters AND not in the common-surname blocklist above - matching
    "Jones" or "Smith" alone against an NFL news cycle produces real
    false positives (confirmed live: "Daniel Jones" matched a Jerry Jones
    headline), and under-matching is the safer failure mode than a
    misattributed headline.
    """
    if not name or " " not in name.strip():
        return []
    full_name = name.lower()
    full_matches = [headline for headline in headlines if full_name in headline["title"].lower()]
    if full_matches:
        return full_matches
    surname = name.split()[-1].lower()
    if len(surname) < 5 or surname in _COMMON_SURNAMES_EXCLUDED_FROM_FALLBACK:
        return []
    return [headline for headline in headlines if surname in headline["title"].lower()]


def require_fantasy_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    token = get_settings().fantasy_api_token
    if not token or credentials is None or credentials.scheme.lower() != "bearer" or credentials.credentials != token:
        raise HTTPException(status_code=401, detail="Fantasy API authentication required")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create the API-owned pooled engine only in the Uvicorn process. Celery
    # tasks intentionally use get_worker_db() instead (constraint #1).
    get_api_engine()
    try:
        yield
    finally:
        await dispose_api_engine()


app = FastAPI(title="Fantasy Edge", version="0.1.0", lifespan=lifespan)
app.add_middleware(PerformanceMiddleware)


@app.get('/operations/performance', dependencies=[Depends(require_fantasy_token)])
async def performance():
    return performance_snapshot()

# /props, /props/best, /signals, /rankings/{sport}, /parlays - the contract
# homelab-dashboard's Fantasy tile expects (src/tiles/fantasy/client.ts
# there). Now token-gated like /api/v1/fantasy/* below: both this API and
# homelab-dashboard's tile are directly reachable over the public
# sports-api.camptwright.com tunnel, so "read-only" is not the same as
# "safe to leave unauthenticated" - see homelab security audit 2026-09-09.
# homelab-dashboard's client sends FANTASY_API_TOKEN as a Bearer header
# server-side; it already treats a non-OK response as "offline" (client.ts's
# edgeFetch), so this fails quiet there, not hard, if the token is unset.
app.include_router(sportsbook_router, dependencies=[Depends(require_fantasy_token)])
app.include_router(nfl_predictor_router, dependencies=[Depends(require_fantasy_token)])
app.include_router(ledger_router, dependencies=[Depends(require_fantasy_token)])


@app.get("/health", tags=["operations"])
@app.get("/api/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Report only process and database reachability; never provider health."""
    async with get_api_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok", "scope": "+".join(get_settings().supported_sports)}


@app.post("/api/v1/fantasy/sync", dependencies=[Depends(require_fantasy_token)])
async def sync_fantasy(db: AsyncSession = Depends(get_db)) -> dict[str, dict[str, int]]:
    try:
        return await sync_sleeper_account(db)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/fantasy/sync/espn", dependencies=[Depends(require_fantasy_token)])
async def sync_fantasy_espn(db: AsyncSession = Depends(get_db)) -> dict[str, dict[str, int | str]]:
    try:
        return await sync_espn_fantasy_account(db)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/fantasy/leagues", dependencies=[Depends(require_fantasy_token)])
async def fantasy_leagues(db: AsyncSession = Depends(get_db)) -> dict:
    leagues = (await db.scalars(select(SleeperLeague).order_by(SleeperLeague.name))).all()
    return {"items": [{"league_id": item.league_id, "platform": item.platform, "sport": item.sport, "name": item.name, "season": item.season, "status": item.status, "roster_positions": item.roster_positions, "settings": item.settings, "scoring_settings": item.scoring_settings, "synced_at": item.synced_at} for item in leagues]}


@app.get("/api/v1/fantasy/leagues/{league_id}", dependencies=[Depends(require_fantasy_token)])
async def fantasy_league(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league_id))).all()
    return {"league": {"league_id": league.league_id, "name": league.name, "settings": league.settings, "scoring_settings": league.scoring_settings, "roster_positions": league.roster_positions}, "rosters": [{"roster_id": row.roster_id, "owner_id": row.owner_id, "starters": row.starters, "players": row.players, "settings": row.settings} for row in rosters], "snapshots": [{"week": row.week, "kind": row.kind, "payload": row.payload, "synced_at": row.synced_at} for row in snapshots]}


@app.get("/api/v1/fantasy/leagues/{league_id}/analysis", dependencies=[Depends(require_fantasy_token)])
async def fantasy_analysis(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    settings, scoring = league.settings, league.scoring_settings
    insights = []
    if scoring.get("rec"):
        insights.append({"kind": "scoring", "title": f"{scoring['rec']}-PPR scoring", "detail": "Rank receiving volume in start/sit and waiver analysis."})
    if settings.get("waiver_budget", 0):
        insights.append({"kind": "waivers", "title": f"${settings['waiver_budget']} FAAB budget", "detail": "Waiver advice will provide bid ranges."})
    if "SUPER_FLEX" in league.roster_positions:
        insights.append({"kind": "lineup", "title": "Superflex", "detail": "Quarterback scarcity must influence lineup and draft values."})
    if settings.get("max_keepers", 0):
        insights.append({"kind": "draft", "title": f"{settings['max_keepers']} keeper limit", "detail": "Draft scoring must include keeper and future-pick context."})
    return {"league_id": league_id, "insights": insights, "status": "data_ready", "next": "Add projections and sourced news before player-specific recommendations."}


# Slots that accept more than one exact position, keyed to the set of
# positions eligible to fill them. BN/IR/TAXI are reserve slots, never
# part of the starting lineup math below.
FLEX_ELIGIBILITY: dict[str, set[str]] = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
RESERVE_SLOTS = {"BN", "IR", "TAXI"}


def build_starting_lineup(roster: list[dict], roster_positions: list[str], points_key: str = "projected_points") -> tuple[list[dict], list[dict]]:
    """Greedily assigns the highest-projected eligible player to each real
    starting slot in this league's own roster_positions (not a hardcoded
    assumption - every league's actual synced shape, standard or
    SUPER_FLEX). Exact-position slots (QB, RB, WR, TE, K, DEF) are filled
    before FLEX-type slots, and among FLEX-types the most permissive
    (SUPER_FLEX) is filled last, so a flexible slot never claims a player
    who had nowhere else to go before a stricter slot gets its turn.

    This is a practical heuristic - highest points into the most
    restrictive open slot first - not a guaranteed-optimal assignment;
    true optimality needs weighted bipartite matching, which is overkill
    for 9-20 roster slots and would obscure *why* a lineup was chosen.
    A slot with no eligible player left in the pool is returned with
    player: None rather than silently dropped, so a real roster gap is
    visible instead of hidden.

    points_key selects which projection ranks the pool - "projected_points"
    (Sleeper) by default, or "custom_projected_points" to build the
    alternate lineup the second model would pick, so the two can be
    diffed for lineup suggestions. A None value (unmodeled position, no
    2025 history) ranks as 0 here, ranking-only - never displayed as a
    fabricated real zero.
    """
    starting_slots = [slot for slot in roster_positions if slot not in RESERVE_SLOTS]

    def slot_priority(slot: str) -> tuple[int, int]:
        if slot not in FLEX_ELIGIBILITY:
            return (0, 0)
        return (1, len(FLEX_ELIGIBILITY[slot]))

    fill_order = sorted(range(len(starting_slots)), key=lambda i: slot_priority(starting_slots[i]))
    pool = sorted(roster, key=lambda player: player.get(points_key) or 0, reverse=True)
    assigned_ids: set[str] = set()
    lineup_by_index: dict[int, dict] = {}
    for index in fill_order:
        slot = starting_slots[index]
        eligible = FLEX_ELIGIBILITY.get(slot, {slot})
        pick = next((player for player in pool if player["player_id"] not in assigned_ids and player.get("position") in eligible), None)
        if pick:
            assigned_ids.add(pick["player_id"])
            lineup_by_index[index] = pick
    starting_lineup = [{"slot": starting_slots[i], "player": lineup_by_index.get(i)} for i in range(len(starting_slots))]
    bench = [player for player in pool if player["player_id"] not in assigned_ids]
    return starting_lineup, bench


async def _score_league_players(league: "SleeperLeague", latest: dict, db: AsyncSession) -> tuple[dict, dict]:
    """Shared player-scoring core, factored out of _build_fantasy_view so
    the trade calculator/recommender (src/services/trade.py, called from
    the /trade/* routes below) can score ANY roster's players - not just
    "my roster" - with the exact same formula /recommendations and
    /matchup already use. Two independent implementations of "how many
    points does this player score under this league's rules" would
    inevitably drift and produce numbers that don't reconcile across
    pages, which would be far more confusing than the size of this
    shared function.

    Returns (scored_by_id, player_view) - player_view(player_id) is a
    resolver that falls back to 0-point/metadata-only info for a player
    with no current projection row (bye, inactive, newly added),
    matching the fallback every existing per-league endpoint already
    relies on.
    """
    projections = latest.get("projections")
    if projections is None:
        raise HTTPException(status_code=409, detail="run sync to load current projections")
    metadata_snapshot = latest.get("player_metadata")
    metadata_players = metadata_snapshot.payload if metadata_snapshot and isinstance(metadata_snapshot.payload, dict) else {}
    season_averages = await load_exact_2025_averages(db, league.platform, metadata_players)
    def view(item: dict) -> dict:
        info = metadata_players.get(item["player_id"], {})
        stats = item.get("stats") or {}
        points = sum(float(stats.get(key, 0) or 0) * float(weight or 0) for key, weight in league.scoring_settings.items())
        name = " ".join(part for part in [info.get("first_name"), info.get("last_name")] if part)
        return {"player_id": item["player_id"], "name": name, "position": info.get("position"), "team": info.get("team"), "opponent": None, "injury_status": info.get("injury_status"), "projected_points": round(points, 2), "custom_projected_points": custom_projected_points(league.scoring_settings, item["player_id"], season_averages, info.get("position"))}
    rows = projection_rows(projections.payload)
    scored = sorted((view(item) for item in rows), key=lambda item: item["projected_points"], reverse=True)
    scored_by_id = {item["player_id"]: item for item in scored}
    def player_view(player_id: object) -> dict:
        pid = str(player_id)
        if pid in scored_by_id:
            return scored_by_id[pid]
        info = metadata_players.get(pid, {})
        name = " ".join(part for part in [info.get("first_name"), info.get("last_name")] if part) or pid
        return {"player_id": pid, "name": name, "position": info.get("position"), "team": info.get("team"), "opponent": None, "injury_status": info.get("injury_status"), "projected_points": 0.0, "custom_projected_points": custom_projected_points(league.scoring_settings, pid, season_averages, info.get("position"))}
    return scored_by_id, player_view


async def _build_fantasy_view(league_id: str, db: AsyncSession) -> dict:
    """Shared core for /recommendations and /advice: resolves this
    league's current projections into a scored, named player list plus a
    computed starting-lineup/bench split. Both endpoints must reason
    about the exact same players and points - /advice used to rebuild a
    separate, much larger raw payload (200 unscored projection rows) that
    the local LLM could not process in time; see fantasy_advice() below."""
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league_id).order_by(SleeperLeagueSnapshot.week.desc()))).all()
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.kind, snapshot)
    projections = latest.get("projections")
    account = latest.get("account")
    if projections is None or account is None:
        raise HTTPException(status_code=409, detail="run Sleeper sync to load current projections")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    owner_id = account.payload.get("user_id")
    my_roster = next((roster for roster in rosters if roster.owner_id == owner_id), None)
    if my_roster is None:
        raise HTTPException(status_code=409, detail="Sleeper roster ownership is not available yet")
    owned = {player for roster in rosters for player in roster.players}
    scored_by_id, player_view = await _score_league_players(league, latest, db)
    scored = sorted(scored_by_id.values(), key=lambda item: item["projected_points"], reverse=True)
    rows = projection_rows(projections.payload)
    raw_projection_count = len(projections.payload) if isinstance(projections.payload, (dict, list)) else 0
    my_players = [player_view(player_id) for player_id in my_roster.players]
    starting_lineup, bench = build_starting_lineup(my_players, league.roster_positions)
    bench.sort(key=lambda player: player["projected_points"], reverse=True)
    # Lineup suggestions: build the SAME slots using the custom model's
    # ranking instead of Sleeper's, then diff the two picks per slot. A
    # slot where they agree needs no comment; a slot where they disagree
    # is worth a look precisely because it's the two independent sources
    # giving conflicting advice, not one model's opinion alone. This is
    # deterministic (compare two already-computed lineups), not an LLM
    # guess, so it's always available the moment the fixed lineup is.
    custom_lineup, _ = build_starting_lineup(my_players, league.roster_positions, points_key="custom_projected_points")
    lineup_suggestions = []
    for sleeper_entry, custom_entry in zip(starting_lineup, custom_lineup):
        sleeper_pick, model_pick = sleeper_entry["player"], custom_entry["player"]
        sleeper_id = sleeper_pick["player_id"] if sleeper_pick else None
        model_id = model_pick["player_id"] if model_pick else None
        if model_id is not None and model_id != sleeper_id:
            lineup_suggestions.append({
                "slot": sleeper_entry["slot"],
                "sleeper_pick": {"name": sleeper_pick["name"], "projected_points": sleeper_pick["projected_points"]} if sleeper_pick else None,
                "model_pick": {"name": model_pick["name"], "custom_projected_points": model_pick["custom_projected_points"]},
            })
    waivers = [item for item in scored if str(item["player_id"]) not in owned]
    # A waiver candidate is "recommended" if EITHER model projects them at
    # or above your worst currently-STARTING skill/QB player's Sleeper
    # points - i.e. a realistic case they could outproduce someone
    # already in your lineup. Deliberately not position-matched against
    # that exact starter (FLEX/SUPER_FLEX eligibility makes "which
    # starter would this replace" genuinely ambiguous) - this is a
    # coarse "worth a look" signal, not a specific swap instruction;
    # lineup_suggestions above is where specific, slot-matched swaps
    # live. K/DEF are EXCLUDED from this baseline (see the K/DEF gate
    # below for why) - confirmed live 2026-09-10, without this exclusion
    # a real ESPN league's low-scoring DEF (5.41 pts) set the bar low
    # enough that a pile of irrelevant streaming kickers cleared it.
    starting_points = [entry["player"]["projected_points"] for entry in starting_lineup if entry["player"] and entry["player"].get("position") not in ("K", "DEF")]
    worst_starter_points = min(starting_points) if starting_points else 0.0
    # QB needs its own gate: confirmed live 2026-09-09, without this every
    # unrostered backup QB "beat the worst starter" (usually the kicker,
    # ~6-8 pts, trivially cleared by any real QB's 15-19) and flooded a
    # standard 1-QB league's recommendations with QBs nobody could
    # actually start - a bench QB has zero real value there regardless of
    # how many points it projects. Only worth flagging if this league can
    # actually start a second QB (SUPER_FLEX, or a league with 2+ direct
    # QB slots).
    can_start_second_qb = league.roster_positions.count("QB") > 1 or "SUPER_FLEX" in league.roster_positions
    # K/DEF need a DIFFERENT gate, not the QB one: every league here has
    # exactly one K and one DEF slot (there's no "second kicker" case to
    # gate on), so the real bug wasn't a missing slot - it was comparing
    # a streaming kicker/defense against the WRONG baseline. Confirmed
    # live 2026-09-10 against a real ESPN league: comparing candidate
    # kickers against the single worst-starter-overall number (there, the
    # team's own low-scoring DEF) flagged several kickers that projected
    # BELOW the team's actual kicker as "recommended" purely because they
    # beat an unrelated position's number. A K/DEF swap only ever makes
    # sense compared against the specific K/DEF already in that slot, so
    # each is position-matched against the CURRENT starter there instead
    # of the cross-position floor every other waiver candidate uses.
    current_starter_by_position: dict[str, float] = {}
    for entry in starting_lineup:
        player = entry["player"]
        position = player.get("position") if player else None
        if position in ("K", "DEF"):
            current_starter_by_position[position] = player["projected_points"]
    for player in waivers:
        best = max(player["projected_points"], player["custom_projected_points"] or 0.0)
        position = player.get("position")
        if position in ("K", "DEF"):
            current = current_starter_by_position.get(position, 0.0)
            player["recommended"] = current > 0 and best > current
        else:
            eligible_slot_exists = position != "QB" or can_start_second_qb
            player["recommended"] = best >= worst_starter_points and worst_starter_points > 0 and eligible_slot_exists
    # A "recommended" flag alone doesn't tell you WHO to cut to make room
    # or HOW MUCH to bid - the two questions that actually decide whether
    # someone acts on it. drop_candidate is always your single weakest
    # bench player by best-of-both-models value (not position-matched -
    # a bench slot is generic roster space in every league synced here,
    # not locked to one position), so it's a real, always-current name
    # rather than a placeholder. suggested_faab_bid is a simple tiered
    # percentage of this league's real waiver_budget scaled by how much
    # the pickup projects to beat the baseline it cleared - a heuristic
    # explicitly labeled as one, not a claim of modeling how this
    # league's specific bidders will actually behave this week.
    weakest_bench_value = lambda p: max(p["projected_points"], p.get("custom_projected_points") or 0.0)
    weakest_bench = min(bench, key=weakest_bench_value) if bench else None
    waiver_budget = league.settings.get("waiver_budget") or 0
    def faab_bid(edge: float) -> int | None:
        if waiver_budget <= 0:
            return None
        tier = 0.05 if edge < 2 else 0.10 if edge < 5 else 0.20 if edge < 10 else 0.35
        return max(1, round(waiver_budget * tier))
    for player in waivers:
        if not player["recommended"]:
            player["drop_candidate"] = None
            player["suggested_faab_bid"] = None
            continue
        best = max(player["projected_points"], player["custom_projected_points"] or 0.0)
        baseline = current_starter_by_position.get(player.get("position"), worst_starter_points) if player.get("position") in ("K", "DEF") else worst_starter_points
        player["drop_candidate"] = {"player_id": weakest_bench["player_id"], "name": weakest_bench["name"], "position": weakest_bench.get("position"), "projected_points": weakest_bench["projected_points"]} if weakest_bench else None
        player["suggested_faab_bid"] = faab_bid(best - baseline)
    # News matching is deterministic string-matching (see
    # match_player_news()), not an LLM call, so every player everywhere -
    # the recommendations page's lineup/bench/waivers, not just the
    # /advice narrative - gets real, reliably-matched headlines with zero
    # hallucination risk and zero added latency. Configuring RSS sources
    # is optional here (unlike /advice, which also needs LiteLLM
    # configured) - an empty settings.fantasy_news_rss_urls just means
    # every player's news list stays empty rather than the whole
    # recommendations endpoint failing.
    settings = get_settings()
    headlines = await fetch_rss_headlines(settings.fantasy_news_rss_urls) if settings.fantasy_news_rss_urls else []
    def attach_news(player: dict) -> dict:
        return {**player, "news": match_player_news(player["name"], headlines)}
    starting_lineup = [{"slot": entry["slot"], "player": attach_news(entry["player"]) if entry["player"] else None} for entry in starting_lineup]
    bench = [attach_news(player) for player in bench]
    waivers = [attach_news(player) for player in waivers]
    return {
        "league": league,
        "week": projections.week,
        "starting_lineup": starting_lineup,
        "bench": bench,
        "waivers": waivers,
        "lineup_suggestions": lineup_suggestions,
        "rows": rows,
        "raw_projection_count": raw_projection_count,
        "headlines": headlines,
    }


@app.get("/api/v1/fantasy/leagues/{league_id}/recommendations", dependencies=[Depends(require_fantasy_token)])
async def fantasy_recommendations(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Rank current Sleeper projections using this league's actual scoring.

    These are decision-support rankings, not fabricated news or guaranteed
    outcomes. Player-specific narrative is added only once a sourced-news
    integration is configured.
    """
    view_data = await _build_fantasy_view(league_id, db)
    league = view_data["league"]
    rows = view_data["rows"]
    projection_source = "Sleeper"
    projection_status = "ready" if rows else "source_pending"
    return {
        "league_id": league_id,
        "week": view_data["week"],
        "roster_positions": league.roster_positions,
        "starting_lineup": view_data["starting_lineup"],
        "bench": view_data["bench"],
        "waivers": view_data["waivers"][:15],
        "lineup_suggestions": view_data["lineup_suggestions"],
        "projection_status": projection_status,
        "projection_source": projection_source,
        "projection_records": len(rows),
        "notes": [
            f"{projection_source} projections are scored using the synced Sleeper scoring settings.",
            "Starting lineup is computed from this league's real roster_positions, not assumed - exact-position slots are filled before FLEX/SUPER_FLEX so a flex slot never displaces a player with nowhere else to go.",
            "Waiver candidates exclude all currently rostered player IDs.",
            "Injury status is from the Sleeper projection payload; add sourced news before automated narrative advice.",
            "\"Our model\" is each player's own 2025 season per-game average (passing/rushing/receiving only), scored under this league's rules - a second, independent number to compare against Sleeper's, not a claim it is more accurate. \"model n/a\" means the position isn't modeled (K/DEF) or no 2025 NFL history was found for that name.",
        ] if rows else [
            f"{projection_source} returned {view_data['raw_projection_count']:,} player records for week {view_data['week']}, but no usable projection records.",
            "Your roster, league rules, and actual matchup scoring are still synced from Sleeper.",
            "Start/sit and waiver rankings will appear once a licensed projection source supplies player-level data.",
        ],
    }


@app.get("/api/v1/fantasy/leagues/{league_id}/draft-score", dependencies=[Depends(require_fantasy_token)])
async def draft_score(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Transparent roster-construction score; not a claim of player value."""
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league_id).order_by(SleeperLeagueSnapshot.week.desc()))).all()
    projection = next((row for row in snapshots if row.kind == "projections"), None)
    account = next((row for row in snapshots if row.kind == "account"), None)
    if projection is None or account is None:
        raise HTTPException(status_code=409, detail="run Sleeper sync to calculate draft score")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    mine = next((row for row in rosters if row.owner_id == account.payload.get("user_id")), None)
    if mine is None:
        raise HTTPException(status_code=409, detail="your roster is not available")
    metadata = next((row for row in snapshots if row.kind == "player_metadata"), None)
    metadata_players = metadata.payload if metadata and isinstance(metadata.payload, dict) else {}
    positions = {
        str(row.get("player_id")): (row.get("player") or {}).get("position")
        for row in projection_rows(projection.payload)
    }
    # Player metadata remains useful even before Sleeper exposes weekly
    # projection details, so roster construction does not depend on a vendor
    # feed being populated.
    positions.update({str(player_id): row.get("position") for player_id, row in metadata_players.items() if isinstance(row, dict)})
    roster_positions = [slot for slot in league.roster_positions if slot not in {"BN", "IR", "TAXI"}]
    direct = [slot for slot in roster_positions if slot not in {"FLEX", "SUPER_FLEX"}]
    owned_positions = [positions.get(str(player)) for player in mine.players]
    required, available = Counter(direct), Counter(position for position in owned_positions if position)
    covered = sum(min(required[position], available[position]) for position in required)
    score = round(100 * covered / max(1, len(direct)))
    return {"league_id": league_id, "score": score, "method": "percentage of direct starting-position requirements represented on your roster; FLEX/SUPER_FLEX depth is reported separately, not guessed", "covered_direct_slots": covered, "required_direct_slots": len(direct), "starter_slots": roster_positions, "roster_size": len(mine.players), "position_source": "Sleeper player metadata" if metadata_players else "weekly projection payload"}


@app.get("/api/v1/fantasy/leagues/{league_id}/matchup", dependencies=[Depends(require_fantasy_token)])
async def fantasy_matchup(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Return the signed-in Sleeper roster's current matchup without guesses."""
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league_id).order_by(SleeperLeagueSnapshot.week.desc()))).all()
    latest = {}
    for row in snapshots:
        latest.setdefault(row.kind, row)
    account, matchups = latest.get("account"), latest.get("matchups")
    if account is None or matchups is None or not isinstance(matchups.payload, list):
        raise HTTPException(status_code=409, detail="run Sleeper sync to load the current matchup")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    mine = next((row for row in rosters if row.owner_id == account.payload.get("user_id")), None)
    if mine is None:
        raise HTTPException(status_code=409, detail="Sleeper roster ownership is not available yet")
    mine_row = next((row for row in matchups.payload if isinstance(row, dict) and row.get("roster_id") == mine.roster_id), None)
    if mine_row is None:
        raise HTTPException(status_code=409, detail="your current matchup is not available")
    opponent = next((row for row in matchups.payload if isinstance(row, dict) and row.get("matchup_id") == mine_row.get("matchup_id") and row.get("roster_id") != mine.roster_id), None)
    metadata = latest.get("player_metadata")
    players = metadata.payload if metadata and isinstance(metadata.payload, dict) else {}
    # Real ("points") scoring is 0 for every roster in the league until
    # games actually kick off (confirmed live 2026-09-09 against Sleeper's
    # own /league/{id}/matchups/{week} - every roster_id, not just this
    # league's) - which left this page with nothing useful to show before
    # kickoff. Projections come from the SAME "projections" snapshot and
    # scoring-settings math /recommendations already uses (see
    # _build_fantasy_view()'s view()), computed independently here since
    # that helper is scoped to "my roster" only and this page also needs
    # the opponent's projected points, which it never fetches a roster
    # for.
    projections = latest.get("projections")
    projected_points_by_id: dict[str, float] = {}
    if projections is not None:
        for row in projection_rows(projections.payload):
            stats = row.get("stats") or {}
            points = sum(float(stats.get(key, 0) or 0) * float(weight or 0) for key, weight in league.scoring_settings.items())
            projected_points_by_id[row["player_id"]] = round(points, 2)
    # Second, independent projection source - see custom_projection.py.
    season_averages = await load_exact_2025_averages(db, league.platform, players)
    # .get("full_name") was the original raw-Sleeper-catalog field name;
    # the player_metadata snapshot was later trimmed to first_name/
    # last_name (see sleeper.py's widened, size-trimmed metadata) and
    # never carried full_name at all, so every single player here always
    # fell through to the str(player_id) fallback - confirmed live
    # 2026-09-09, this endpoint showed raw numeric IDs as "names" for
    # every player. Matches the same first_name+last_name join already
    # used in fantasy_recommendations()'s view()/owned_player_view().
    def enrich(ids: list) -> list[dict]:
        def info_for(player_id: object) -> dict:
            return players.get(str(player_id)) or {}
        def name_for(player_id: object) -> str:
            info = info_for(player_id)
            return " ".join(part for part in [info.get("first_name"), info.get("last_name")] if part) or str(player_id)
        return [{"player_id": str(player_id), "name": name_for(player_id), "position": info_for(player_id).get("position"), "team": info_for(player_id).get("team"), "projected_points": projected_points_by_id.get(str(player_id), 0.0), "custom_projected_points": custom_projected_points(league.scoring_settings, str(player_id), season_averages, info_for(player_id).get("position"))} for player_id in ids]
    mine_starters = [str(player_id) for player_id in mine.starters]
    mine_projected = round(sum(projected_points_by_id.get(pid, 0.0) for pid in mine_starters), 2)
    opponent_starters = [str(player_id) for player_id in (opponent.get("starters") or [])] if opponent else []
    opponent_projected = round(sum(projected_points_by_id.get(pid, 0.0) for pid in opponent_starters), 2)
    return {"league_id": league_id, "week": matchups.week, "your_roster": {"roster_id": mine.roster_id, "starters": enrich(mine_starters), "bench": enrich([player_id for player_id in mine.players if str(player_id) not in mine_starters]), "points": mine_row.get("points", 0), "projected_points": mine_projected}, "opponent": {"roster_id": opponent.get("roster_id"), "starters": enrich(opponent_starters), "points": opponent.get("points", 0), "projected_points": opponent_projected} if opponent else None}


async def _load_league_and_scoring(league_id: str, db: AsyncSession) -> tuple["SleeperLeague", dict, callable]:
    """Shared prelude for both /trade routes: resolve the league and
    build the same player-scoring resolver every other per-league
    endpoint uses (see _score_league_players)."""
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league_id).order_by(SleeperLeagueSnapshot.week.desc()))).all()
    latest = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.kind, snapshot)
    _, player_view = await _score_league_players(league, latest, db)
    return league, latest, player_view


class TradeEvaluateRequest(BaseModel):
    side_a_player_ids: list[str]
    side_b_player_ids: list[str]


class TradeRosterAdjustment(BaseModel):
    add: list[str] = Field(default_factory=list,max_length=6)
    drop: list[str] = Field(default_factory=list,max_length=6)


class TradeRosterRequest(TradeEvaluateRequest):
    a: TradeRosterAdjustment = Field(default_factory=TradeRosterAdjustment)
    b: TradeRosterAdjustment = Field(default_factory=TradeRosterAdjustment)


@app.get("/api/v1/fantasy/leagues/{league_id}/player-values", dependencies=[Depends(require_fantasy_token)])
async def fantasy_player_values(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    from src.services.fantasy_decision_models import build
    from src.services.fantasy_values import value_board, suggestions
    from starlette.concurrency import run_in_threadpool
    data=value_board(await build(db,league_id,include_catalog=True))
    data['trade_candidates']=await run_in_threadpool(suggestions,data)
    return data


@app.post("/api/v1/fantasy/leagues/{league_id}/trade/roster-impact", dependencies=[Depends(require_fantasy_token)])
async def fantasy_roster_trade(league_id: str, request: TradeRosterRequest, db: AsyncSession = Depends(get_db)) -> dict:
    from src.services.fantasy_decision_models import build
    from src.services.fantasy_values import compare
    if len(request.side_a_player_ids)+len(request.side_b_player_ids)>12:
        raise HTTPException(status_code=400,detail="At most twelve players per comparison")
    data=await build(db,league_id,include_catalog=True)
    from src.services.fantasy_market import selected,cohort
    league=await db.get(SleeperLeague,league_id)
    market=selected(cohort(league,len(data.get('rosters',[]))),league.platform,request.side_a_player_ids+request.side_b_player_ids) if league else {'status':'missing_league'}
    return {**compare(data,request.side_a_player_ids,request.side_b_player_ids,
                     adjustments={'a':request.a.model_dump(),'b':request.b.model_dump()}),'market':market}


@app.get("/api/v1/fantasy/leagues/{league_id}/decision-models", dependencies=[Depends(require_fantasy_token)])
async def fantasy_decision_models(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    from src.services.fantasy_decision_models import build
    from src.services.fantasy_prospective import latest
    from starlette.concurrency import run_in_threadpool
    from src.services.fantasy_specialists import latest as specialist_latest
    return {**await build(db, league_id), 'prospective':await run_in_threadpool(latest),
            'specialist_validation':await run_in_threadpool(specialist_latest,league_id)}


@app.post("/api/v1/fantasy/leagues/{league_id}/trade/ros", dependencies=[Depends(require_fantasy_token)])
async def fantasy_ros_trade(league_id: str, request: TradeEvaluateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    from src.services.fantasy_decision_models import build, trade_comparison
    if len(request.side_a_player_ids)+len(request.side_b_player_ids)>12:
        raise HTTPException(status_code=400, detail="At most twelve players per comparison")
    data=await build(db,league_id)
    return trade_comparison({p['player_id']:p for p in data['players']},request.side_a_player_ids,request.side_b_player_ids)


@app.post("/api/v1/fantasy/leagues/{league_id}/trade/evaluate", dependencies=[Depends(require_fantasy_token)])
async def trade_evaluate(league_id: str, request: TradeEvaluateRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Evaluate any proposed trade between two arbitrary lists of
    player ids in this league - no ownership assumption, so this works
    for "my roster vs. an opponent's" or a trade between two other
    teams you're just sanity-checking."""
    _, _, player_view = await _load_league_and_scoring(league_id, db)
    if not request.side_a_player_ids or not request.side_b_player_ids:
        raise HTTPException(status_code=400, detail="both sides of a trade need at least one player")
    side_a = [player_view(pid) for pid in request.side_a_player_ids]
    side_b = [player_view(pid) for pid in request.side_b_player_ids]
    return {"league_id": league_id, **evaluate_trade(side_a, side_b)}


@app.get("/api/v1/fantasy/leagues/{league_id}/trade/suggestions", dependencies=[Depends(require_fantasy_token)])
async def trade_suggestions(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Suggest realistic trades - 1-for-1 up to 2-for-2 - between my
    roster and every other roster in this league - see
    src/services/trade.py's suggest_trades() for the full method and its
    deliberate conservatism (never offers anyone in a currently-computed
    starting lineup, mine or theirs, skips lopsided value packages)."""
    league, latest, player_view = await _load_league_and_scoring(league_id, db)
    account = latest.get("account")
    if account is None:
        raise HTTPException(status_code=409, detail="run sync to load roster ownership")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    owner_id = account.payload.get("user_id")
    my_roster = next((roster for roster in rosters if roster.owner_id == owner_id), None)
    if my_roster is None:
        raise HTTPException(status_code=409, detail="your roster is not available yet")
    def starter_ids(players: list[dict]) -> set[str]:
        starting_lineup, _ = build_starting_lineup(players, league.roster_positions)
        return {entry["player"]["player_id"] for entry in starting_lineup if entry["player"]}
    my_players = [player_view(pid) for pid in my_roster.players]
    other_rosters = []
    for roster in rosters:
        if roster.roster_id == my_roster.roster_id:
            continue
        players = [player_view(pid) for pid in roster.players]
        other_rosters.append({"roster_id": roster.roster_id, "team_name": roster.team_name, "players": players, "starter_ids": starter_ids(players)})
    suggestions = suggest_trades(my_players, starter_ids(my_players), other_rosters, league.roster_positions)
    return {
        "league_id": league_id,
        "suggestions": suggestions,
        "note": "Suggestions range from 1-for-1 up to 2-for-2, ranked by value fairness then simplicity; trade_value is a directional proxy (this week's Sleeper projection averaged with the season-average model), not a rest-of-season valuation.",
    }


@app.get("/api/v1/fantasy/leagues/{league_id}/trade/rosters", dependencies=[Depends(require_fantasy_token)])
async def trade_rosters(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Every roster in the league with named, scored players - feeds the
    trade calculator's player pickers (the evaluate endpoint itself only
    takes player ids; this is what lets a UI show real names to pick
    from for both sides of a proposed trade, including a trade between
    two OTHER teams)."""
    league, latest, player_view = await _load_league_and_scoring(league_id, db)
    account = latest.get("account")
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    my_owner_id = account.payload.get("user_id") if account else None
    return {
        "league_id": league_id,
        "rosters": [
            {
                "roster_id": roster.roster_id,
                "team_name": roster.team_name or f"Roster {roster.roster_id}",
                "is_mine": roster.owner_id == my_owner_id,
                "players": sorted((player_view(pid) for pid in roster.players), key=lambda p: p["name"]),
            }
            for roster in rosters
        ],
    }


@app.post("/api/v1/fantasy/leagues/{league_id}/advice", dependencies=[Depends(require_fantasy_token)])
async def fantasy_advice(league_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Produce constrained advice from disclosed inputs, never autonomous actions."""
    settings = get_settings()
    if not settings.litellm_api_key or not settings.fantasy_news_rss_urls:
        raise HTTPException(status_code=503, detail="configure LiteLLM and allow-listed RSS sources before requesting advice")
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="league not synced")
    if league.sport != "nfl":
        # fantasy_news_rss_urls is a single NFL-focused feed list (ESPN NFL
        # news, FantasyPros, RotoBaller, ...) and the system prompt below
        # is written for football specifically - labeling NBA advice as
        # sport-aware while still feeding it NFL news would be a more
        # misleading gap than this explicit one.
        raise HTTPException(
            status_code=409,
            detail=f"AI advice is not available for {league.sport} leagues yet - "
            "the configured news sources are NFL-only",
        )
    # Built from the SAME scored/named/lineup-split data /recommendations
    # shows on the page, with news already matched per player by
    # match_player_news() (deterministic substring matching, not the
    # model's job - confirmed live 2026-09-09 that asking this same local
    # model to do that matching itself made it hallucinate one unrelated
    # headline onto every single player). A prior version also sent 200
    # unscored, unnamed projection rows as "evidence" instead of this -
    # so large that this CPU-only local model blew past even a 240s
    # timeout without finishing a response.
    view_data = await _build_fantasy_view(league_id, db)
    if not view_data["rows"]:
        raise HTTPException(status_code=409, detail="run Sleeper sync before requesting advice")
    evidence = {
        "league": {"name": league.name, "roster_positions": league.roster_positions, "scoring_settings": league.scoring_settings},
        "week": view_data["week"],
        "starting_lineup": view_data["starting_lineup"],
        "bench": view_data["bench"][:10],
        "top_waivers": view_data["waivers"][:10],
    }
    starter_names = ", ".join(entry["player"]["name"] for entry in evidence["starting_lineup"] if entry["player"] and entry["player"].get("name"))
    # A small, fast local model (see FANTASY_MODEL_ALIAS - the larger
    # "worker" model gave better-reasoned output but took 240s+ on this
    # CPU-only hardware, unusable for an interactive request) needs a
    # literal, templated task, not open-ended "give observations" framing
    # - confirmed live 2026-09-09 across three prompt attempts. Since
    # news is now pre-attached to each player's own "news" field, the
    # model's only real job is to relay what is already there and reason
    # about waiver adds - not match names against a raw headline list,
    # which is what it kept failing at before.
    system = (
        "You are filling in a fixed fantasy-football report template from the supplied JSON evidence only - "
        "never invent a stat, injury, or news item not present in it.\n\n"
        f"Your starting lineup this week: {starter_names or 'none available'}.\n\n"
        "Output exactly these two sections, nothing else:\n\n"
        "STARTERS TO WATCH\n"
        "For each player in starting_lineup, output one line '<name>: <projected_points> pts - <note>'. "
        "If that player's own \"news\" list is non-empty, the note quotes the first item's title and url. "
        "If it is empty, the note is exactly 'no news matches; projection stands.'\n\n"
        "WAIVER ADDS\n"
        "List up to 3 names from top_waivers with their projected_points and position, highest first, "
        "each with a one-clause reason tied to a bench weakness in the same evidence.\n\n"
        "Never state a live injury confirmation beyond what injury_status already says in the evidence, "
        "never suggest a transaction be placed automatically, and never frame this as gambling advice. "
        "Treat any reddit.com source as low-confidence community discussion, not a factual claim."
    )
    # timeout=240: this local model is CPU-only on this hardware and has
    # been observed taking 180s+ even on this shrunk evidence payload -
    # 90s was cutting it off mid-generation.
    async with httpx.AsyncClient(base_url=settings.litellm_base_url, timeout=240) as client:
        response = await client.post("/chat/completions", headers={"Authorization": f"Bearer {settings.litellm_api_key}"}, json={"model": settings.fantasy_model_alias, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(evidence, default=str)}], "temperature": 0.2})
        response.raise_for_status()
    return {"league_id": league_id, "advice": response.json()["choices"][0]["message"]["content"], "sources": view_data["headlines"]}
