"""PrizePicks' public projections JSON - a second player-props source
alongside Underdog (src/ingest/underdog.py).

One request returns every sport PrizePicks offers as a flat JSON:API
document (`data`/`included`), not just the ones this app supports -
`settings.prizepicks_league_sports` filters it down, mirroring
underdog_api.py's `_SPORT_ID_MAP` shape so a later supported_sports
addition needs no code change here either.

PrizePicks is a fixed-payout pick'em product, not a sportsbook: it has no
American-odds price at all, only a line. `over_price_american`/
`under_price_american` stay null rather than a fabricated value, matching
this codebase's standing "never fabricate" rule (see /props/best's own
note in src/api/routers/sportsbook.py).

Each projection also carries an `odds_type` ("standard"|"goblin"|"demon")
and can be a promotional line (`is_promo`) or a single-sided special
(`allowed_wager_types` other than "under_or_over"). Only `standard`,
non-promotional, two-sided projections are PrizePicks' real, comparable
line - goblin/demon are easier/harder alternates at different points, and
promo lines (e.g. "free_square") are not genuine market prices.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.data.scrapers.base import BaseScraper, ScraperError
from src.ingest.identity import resolve_player
from src.ingest.lines import record_prop_line
from src.ingest.runs import record_run
from src.utils.normalize import normalize_stat_type

SOURCE = "prizepicks"


class PrizePicksScraper(BaseScraper):
    source = SOURCE
    min_interval = 3.0


async def ingest_props(db: AsyncSession) -> tuple[int, int]:
    """Returns (rows_written, parked_count)."""
    settings = get_settings()
    scraper = PrizePicksScraper()

    async with record_run(db, SOURCE) as run:
        try:
            payload = await scraper.fetch_json(
                settings.prizepicks_base_url,
                params={"per_page": 1000, "new_player": "true"},
            )
        except ScraperError as exc:
            run.detail = str(exc)
            raise RuntimeError(str(exc)) from None

        included = payload.get("included") or []
        players = {i["id"]: i["attributes"] for i in included if i["type"] == "new_player"}
        leagues = {i["id"]: i["attributes"].get("name") for i in included if i["type"] == "league"}

        written = 0
        parked = 0
        for projection in payload.get("data") or []:
            attrs = projection.get("attributes") or {}
            if attrs.get("odds_type") != "standard" or attrs.get("is_promo"):
                continue
            if attrs.get("allowed_wager_types") != "under_or_over":
                continue

            line_score = attrs.get("line_score")
            stat_type = attrs.get("stat_type")
            if line_score is None or not stat_type:
                parked += 1
                continue

            league_id = _rel_id(projection, "league")
            sport = settings.prizepicks_league_sports.get(leagues.get(league_id, ""))
            if sport is None or sport not in settings.supported_sports:
                continue

            player_id = _rel_id(projection, "new_player")
            player_attrs = players.get(player_id) if player_id else None
            if not player_attrs or not player_attrs.get("name"):
                parked += 1
                continue

            player = await resolve_player(
                db,
                source=SOURCE,
                external_id=player_id,
                full_name=player_attrs["name"],
                position=player_attrs.get("position"),
                sport=sport,
            )
            if player is None:
                # Unknown or ambiguous - parked, never name-matched (same
                # rule as underdog.py: a wrong match poisons training data
                # silently).
                parked += 1
                continue

            if await record_prop_line(
                db,
                player_id=player.id,
                game_id=None,
                stat_type=normalize_stat_type(stat_type),
                line=float(line_score),
                over_price_american=None,
                under_price_american=None,
                source=SOURCE,
            ):
                written += 1

        run.rows_written = written
        run.detail = f"{parked} projections parked as unresolvable"
        await db.commit()
        return written, parked


def _rel_id(resource: dict[str, Any], relationship: str) -> str | None:
    return ((resource.get("relationships") or {}).get(relationship) or {}).get("data", {}).get("id")
