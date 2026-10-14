"""Anytime-touchdown prices captured for projection research.

Touchdowns carry most of a fantasy score's variance, and the market-implied
projection research (docs/2026-10-12-engine-research.md) could not test them:
only yardage and reception lines were collected. ParlayAPI bills a flat three
credits per props page whatever the markets, and a whole NFL week fits one
page (probe 2026-10-14: 738 rows, limit 5000), so the existing NFL call now
also asks for player_anytime_td at no extra cost.

The prices are not offers. DraftKings and Caesars quote only the Yes side
(probe: 649 rows, none two-sided); Pinnacle quotes both but for few players.
A Yes-only price has no observed hold, and ParlayAPI's docs say not to derive
the No price, so these rows stay out of player_prop_lines and every betting
path. They are frozen create-only under projection-engine/market-td for
research; how to remove the hold (Pinnacle overlap, or scaling a game's
probabilities to its implied touchdown total) is a research question, not a
serving rule.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select

from src.models.identity import Player

MARKET = "player_anytime_td"
BOOKS = {"draftkings", "betmgm", "caesars", "pinnacle"}


def archive_root():
    from src.services.projection_engine_prospective import archive_root as engine_root
    return engine_root() / "market-td"


def _stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _price(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) >= 100 else None


def implied(american: int) -> float:
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def extract(payload) -> list[dict]:
    """Sportsbook anytime-TD rows with a real Yes price; the No price kept only when quoted."""
    rows = []
    for item in payload if isinstance(payload, list) else []:
        if (item.get("market_key") != MARKET or item.get("bookmaker") not in BOOKS or item.get("line") != 0.5
                or item.get("period", "FULL") != "FULL" or item.get("is_dfs_flat_payout") is not False
                or item.get("dfs_normalized") is not False or item.get("commence_time_reported") is not True):
            continue
        yes, updated = _price(item.get("over_price")), _stamp(item.get("last_update"))
        if yes is None or updated is None or not item.get("player"):
            continue
        rows.append({"event": item, "name": item["player"], "book": item["bookmaker"], "yes": yes,
                     "no": _price(item.get("under_price")), "updated": updated})
    return rows


async def capture(db, sport: str, payload, now: datetime) -> dict:
    from src.ingest.prop_events import match_priced_event
    from src.ingest.theodds_props import select_player
    from src.services.roster_stat_prospective import publish
    rows = extract(payload)
    if not rows:
        return {"td_rows": 0, "td_captured": 0}
    players = list((await db.scalars(select(Player).where(Player.sport == sport))).all())
    games, written, unmatched = {}, 0, 0
    for row in rows:
        event = row["event"]
        key = (event.get("home_team"), event.get("away_team"), event.get("commence_time"))
        if key not in games:
            games[key] = await match_priced_event(db, event, sport)
        game = games[key]
        player = select_player(players, row["name"], game) if game else None
        if (game is None or player is None or game.status != "scheduled" or game.game_time is None
                or game.game_time <= now):
            unmatched += 1
            continue
        rid = hashlib.sha256(f"td:{game.id}:{player.id}:{row['book']}:{row['updated'].isoformat()}".encode()).hexdigest()
        written += bool(publish(archive_root() / "quotes" / f"{rid}.json", {
            "id": rid, "market": MARKET, "book": row["book"], "yes": row["yes"], "no": row["no"],
            "source_updated_at": row["updated"].isoformat(), "captured_at": now.isoformat(),
            "game_id": str(game.id), "season": game.season, "week": game.week,
            "kickoff": game.game_time.isoformat(), "player_id": str(player.id), "name": row["name"],
            "serving_promoted": False}))
    return {"td_rows": len(rows), "td_captured": written, "td_unmatched": unmatched}


def frozen(root=None) -> dict[tuple[str, str, str], dict]:
    """Latest pre-kickoff quote per (game_id, player_id, book)."""
    root = root or archive_root()
    out = {}
    for path in (root / "quotes").glob("*.json"):
        r = json.loads(path.read_text())
        if _stamp(r["source_updated_at"]) >= _stamp(r["kickoff"]):
            continue
        key = (r["game_id"], r["player_id"], r["book"])
        if key not in out or r["source_updated_at"] > out[key]["source_updated_at"]:
            out[key] = r
    return out
