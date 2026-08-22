"""Underdog Fantasy's public API - the primary props source (CONSTRAINT #5).

PrizePicks sits behind PerimeterX bot protection and must not be scraped; the
Odds API's player-prop markets are a paid tier we don't have. Underdog
publishes an unauthenticated JSON endpoint that lists every current pick,
which is why it's the only props source in this codebase.

Verified against the live endpoint (2026-08-02): the response is a single
document with five sibling top-level arrays - `over_under_lines`,
`appearances`, `players`, `games`, `solo_games` - not the self-contained
per-line objects an API-docs skim would suggest. A prop line names a player
only indirectly: `line.over_under.appearance_stat.appearance_id` points into
`appearances`, and `appearances[].player_id` points into `players`. There is
no `teams` array, so a player's team name is not resolvable from this
endpoint at all - `players[].team_id` is an opaque UUID with nothing to
join it against here.

This module only fetches and flattens. Normalisation (constraint #8) and
dedup (constraint #6) happen in props_agent.py, which is the layer that
knows about the database.
"""

from __future__ import annotations

from typing import Any

import httpx

# Public, unauthenticated. Underdog serves this to their own web client.
APPEARANCES_URL = "https://api.underdogfantasy.com/beta/v6/over_under_lines"

# Underdog's player.sport_id values, confirmed against the live payload
# (NFL, TENNIS, MLB, CS, CFB, ESPORTS, VAL, LOL, MMA, WNBA, NPB all observed).
# College football is "CFB", not "NCAAF"; college basketball has not been
# observed in-sample (off-season) so both plausible codes are mapped.
# Unmapped sport_ids (tennis, esports, MMA, NPB, ...) are intentionally
# dropped - Fantasy Edge does not model them.
_SPORT_ID_MAP = {
    "NFL": "nfl",
    "NBA": "nba",
    "WNBA": "wnba",
    "CFB": "ncaaf",
    "CBB": "ncaam",
    "NCAAB": "ncaam",
    "NHL": "nhl",
    "MLB": "mlb",
}


async def get_over_under_lines() -> dict[str, Any]:
    """The full Underdog document: over_under_lines plus the appearances/
    players arrays needed to resolve who each line is about.

    There's no per-sport endpoint - Underdog returns everything in one call,
    so props_agent fetches once and filters client-side.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(APPEARANCES_URL)
        response.raise_for_status()
        return response.json()


def raw_lines_to_props(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Underdog's document into one dict per (player, stat) line,
    with over/under prices already paired - what props_agent needs to build
    one PlayerPropLine row.

    Lines whose category isn't `player_prop` (game lines, etc.), or whose
    appearance/player can't be resolved, or whose sport isn't one we model,
    are silently skipped.
    """
    appearances_by_id = {a["id"]: a for a in payload.get("appearances", [])}
    players_by_id = {p["id"]: p for p in payload.get("players", [])}

    rows: list[dict[str, Any]] = []
    for line in payload.get("over_under_lines", []):
        over_under = line.get("over_under") or {}
        if over_under.get("category") != "player_prop":
            continue

        appearance_stat = over_under.get("appearance_stat") or {}
        appearance = appearances_by_id.get(appearance_stat.get("appearance_id"))
        if appearance is None:
            continue
        player = players_by_id.get(appearance.get("player_id"))
        if player is None:
            continue

        sport = _SPORT_ID_MAP.get(player.get("sport_id"))
        if sport is None:
            continue

        stat_display = appearance_stat.get("display_stat")
        stat_value = line.get("stat_value")
        player_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        if not stat_display or stat_value is None or not player_name:
            continue

        over_price = None
        under_price = None
        for opt in line.get("options") or []:
            american = opt.get("american_price")
            if american is None:
                continue
            choice = (opt.get("choice") or "").lower()
            if choice in ("higher", "over"):
                over_price = int(american)
            elif choice in ("lower", "under"):
                under_price = int(american)

        rows.append(
            {
                "sport": sport,
                "source": "underdog",
                "player_name": player_name,
                # Stable per-player identifier for the crosswalk. Names are
                # not unique (two active Josh Allens), so this is what
                # resolve_player keys on.
                "underdog_player_id": str(player.get("id") or ""),
                # No `teams` array in this payload - team_id can't be
                # resolved to a name here, so game_id matching in
                # props_agent falls back to player-only resolution.
                "team_name": None,
                "raw_stat_type": stat_display,
                "line": float(stat_value),
                "over_price_american": over_price,
                "under_price_american": under_price,
            }
        )
    return rows
