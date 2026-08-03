"""CONSTRAINT #3: class name is `ClvTracker`.

Backfills closing-line value onto settled `BetSignal` rows. Runs on a
schedule (see `celery_app.py`) well after games would have started, looking
for signals that don't have `clv_percent` yet and whose game has since
gone final - at that point the market has stopped moving and the latest
`odds_snapshots` row for that book/market/outcome IS the closing line by
definition (nothing was captured after kickoff).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.algorithms.clv import calculate_clv
from src.models.orm import BetSignal, Game, OddsSnapshot
from src.utils.logging import get_logger

log = get_logger(__name__)


class ClvTracker:
    async def _closing_price(
        self, db: AsyncSession, signal: BetSignal
    ) -> tuple[int, float] | None:
        result = await db.execute(
            select(OddsSnapshot.price_american, OddsSnapshot.implied_probability)
            .where(
                OddsSnapshot.game_id == signal.game_id,
                OddsSnapshot.market == signal.market,
                OddsSnapshot.bookmaker == signal.bookmaker,
                OddsSnapshot.outcome == signal.selection,
            )
            .order_by(OddsSnapshot.captured_at.desc())
            .limit(1)
        )
        row = result.first()
        if row is None or row[0] is None:
            return None
        return int(row[0]), row[1]

    async def update_signal_clv(self, db: AsyncSession, signal: BetSignal) -> bool:
        if signal.price_american is None:
            return False
        closing = await self._closing_price(db, signal)
        if closing is None:
            return False
        closing_price, closing_implied = closing

        clv = calculate_clv(signal.price_american, closing_price)
        await db.execute(
            BetSignal.__table__.update()
            .where(BetSignal.id == signal.id)
            .values(
                closing_price_american=closing_price,
                closing_implied_probability=closing_implied,
                clv_percent=clv.clv_percent,
                clv_captured_at=datetime.now(tz=timezone.utc),
            )
        )
        return True

    async def backfill_pending(self, db: AsyncSession, sport: str, *, limit: int = 200) -> int:
        """Signals attached to a now-final game that haven't had CLV
        computed yet. Called on a schedule, not synchronously with
        ValueAgent - the closing line by definition doesn't exist until the
        game has actually started, which is always later than signal
        creation time.
        """
        result = await db.execute(
            select(BetSignal)
            .join(Game, Game.id == BetSignal.game_id)
            .where(
                BetSignal.sport == sport,
                BetSignal.clv_percent.is_(None),
                Game.status == "final",
            )
            .limit(limit)
        )
        signals = result.scalars().all()
        updated = 0
        for signal in signals:
            if await self.update_signal_clv(db, signal):
                updated += 1
        await db.commit()
        log.info("clv_tracker.backfilled", sport=sport, updated=updated, checked=len(signals))
        return updated
