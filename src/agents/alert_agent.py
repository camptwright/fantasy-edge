"""CONSTRAINT #3: class name is `AlertAgent`.

Posts tiered Discord embeds for `BetSignal` rows and enforces a cooldown so
the same edge doesn't re-alert every time `OddsMonitor` detects another small
line move on a game ValueAgent already flagged. The cooldown key is the
signal's identity (game + market + selection), not the signal row's id, so
it correctly suppresses a second alert for what's functionally "the same
bet" even though ValueAgent inserts a fresh `BetSignal` row each run rather
than updating one in place (see value_agent.py's docstring on why).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.data.cache.redis_client import KEY_ALERT_COOLDOWN, get_redis
from src.models.orm import BetSignal, Game
from src.utils.logging import get_logger

log = get_logger(__name__)

ALERT_COOLDOWN_SECONDS = 3600

_TIER_COLOR = {
    "elite": 0xF1C40F,  # gold
    "strong": 0x2ECC71,  # green
    "standard": 0x3498DB,  # blue
}
_TIER_EMOJI = {"elite": "🔥", "strong": "✅", "standard": "📈"}


class AlertAgent:
    async def _cooldown_key(self, signal: BetSignal) -> str:
        return KEY_ALERT_COOLDOWN.format(
            signal_key=f"{signal.game_id}:{signal.market}:{signal.selection}"
        )

    async def _build_embed(self, db: AsyncSession, signal: BetSignal) -> dict:
        game = await db.get(Game, signal.game_id)
        matchup = (
            f"{game.away_team_name} @ {game.home_team_name}" if game else "Unknown matchup"
        )
        tier_label = signal.tier or "standard"
        emoji = _TIER_EMOJI.get(tier_label, "📈")

        fields = [
            {"name": "Selection", "value": signal.selection, "inline": True},
            {"name": "Book", "value": signal.bookmaker, "inline": True},
            {
                "name": "Price",
                "value": f"{signal.price_american:+d}" if signal.price_american else "n/a",
                "inline": True,
            },
            {"name": "EV%", "value": f"{signal.ev_percent:.1f}%", "inline": True},
            {
                "name": "Model prob",
                "value": f"{signal.model_probability * 100:.1f}%",
                "inline": True,
            },
            {"name": "Confidence", "value": signal.confidence or "n/a", "inline": True},
        ]
        if signal.stake_units:
            fields.append(
                {
                    "name": "Suggested stake",
                    "value": f"{signal.stake_units * 100:.2f}% of bankroll",
                    "inline": True,
                }
            )

        return {
            "title": f"{emoji} {tier_label.upper()} value: {signal.sport.upper()} {signal.market}",
            "description": matchup,
            "color": _TIER_COLOR.get(tier_label, 0x95A5A6),
            "fields": fields,
        }

    async def send_signal_alert(self, db: AsyncSession, signal: BetSignal) -> bool:
        """Returns True if an alert was actually posted (False if
        cooldown-suppressed or no webhook configured)."""
        settings = get_settings()
        if not settings.discord_webhook_url:
            log.info("alert_agent.no_webhook_configured", signal_id=str(signal.id))
            return False

        redis = get_redis()
        key = await self._cooldown_key(signal)
        acquired = await redis.set(key, "1", nx=True, ex=ALERT_COOLDOWN_SECONDS)
        if not acquired:
            log.info("alert_agent.cooldown_suppressed", signal_id=str(signal.id))
            return False

        embed = await self._build_embed(db, signal)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.discord_webhook_url, json={"embeds": [embed]}
            )
            response.raise_for_status()

        await db.execute(
            BetSignal.__table__.update()
            .where(BetSignal.id == signal.id)
            .values(alerted_at=datetime.now(tz=timezone.utc))
        )
        await db.commit()
        log.info("alert_agent.sent", signal_id=str(signal.id), tier=signal.tier)
        return True

    async def send_by_id(self, db: AsyncSession, signal_id: str) -> bool:
        result = await db.execute(select(BetSignal).where(BetSignal.id == signal_id))
        signal = result.scalar_one_or_none()
        if signal is None:
            log.warning("alert_agent.signal_not_found", signal_id=signal_id)
            return False
        return await self.send_signal_alert(db, signal)
