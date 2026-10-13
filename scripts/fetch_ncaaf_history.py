"""Build an FBS game history with closing lines from ESPN's public APIs.

- Scoreboard (site.api.espn.com, groups=80 = FBS) per season/week for games,
  scores and neutral-site flags.
- Odds (sports.core.api.espn.com .../competitions/{id}/odds) per game: the
  first provider's spread (home perspective, negative = home favoured) and
  total, plus the median across providers.

Resumable: each game's odds are cached as JSON under --cache. Polite: a
small concurrency limit and a pause between requests. Output: one CSV row
per completed game.

Usage: python -m scripts.fetch_ncaaf_history --seasons 2016-2025 --cache DIR --out FILE.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
from pathlib import Path

import httpx

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
ODDS = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events/{id}/competitions/{id}/odds"
FIELDS = ["game_id", "season", "week", "season_type", "date", "home", "away", "neutral", "conference_game",
          "home_score", "away_score", "spread_line", "total_line", "providers"]


async def get(client, url, params=None, tries=4):
    for attempt in range(tries):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(1.5 * (attempt + 1))
    return None


async def season_games(client, season):
    games = {}
    for season_type, weeks in ((2, range(1, 17)), (3, range(1, 2))):
        for week in weeks:
            d = await get(client, SCOREBOARD, {"dates": season, "seasontype": season_type, "week": week,
                                                 "groups": 80, "limit": 400})
            for e in (d or {}).get("events", []):
                c = e["competitions"][0]
                if not c.get("status", {}).get("type", {}).get("completed"):
                    continue
                teams = {x["homeAway"]: x for x in c["competitors"]}
                if set(teams) != {"home", "away"}:
                    continue
                games[e["id"]] = {"game_id": e["id"], "season": season, "week": week, "season_type": season_type,
                                  "date": e["date"], "home": teams["home"]["team"]["id"], "away": teams["away"]["team"]["id"],
                                  "neutral": int(bool(c.get("neutralSite"))), "conference_game": int(bool(c.get("conferenceCompetition"))),
                                  "home_score": teams["home"].get("score"), "away_score": teams["away"].get("score")}
            await asyncio.sleep(0.2)
    return games


async def odds(client, game_id, cache: Path, sem):
    path = cache / f"{game_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    async with sem:
        d = await get(client, ODDS.format(id=game_id))
        await asyncio.sleep(0.15)
    items = [i for i in (d or {}).get("items", []) if i.get("spread") is not None or i.get("overUnder") is not None]
    out = {"spreads": [i["spread"] for i in items if isinstance(i.get("spread"), (int, float))],
           "totals": [i["overUnder"] for i in items if isinstance(i.get("overUnder"), (int, float))],
           "first": {"spread": items[0].get("spread"), "total": items[0].get("overUnder")} if items else None}
    path.write_text(json.dumps(out))
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2016-2025")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lo, hi = map(int, a.seasons.split("-"))
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    rows = []
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "fantasy-edge research"}) as client:
        for season in range(lo, hi + 1):
            games = await season_games(client, season)
            results = await asyncio.gather(*(odds(client, gid, cache, sem) for gid in games))
            for g, o in zip(games.values(), results):
                spreads, totals = o["spreads"], o["totals"]
                g["spread_line"] = statistics.median(spreads) if spreads else ""
                g["total_line"] = statistics.median(totals) if totals else ""
                g["providers"] = len(spreads)
                rows.append(g)
            print(season, len(games), sum(1 for g in games.values() if g["spread_line"] != ""), flush=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["date"]))


if __name__ == "__main__":
    asyncio.run(main())
