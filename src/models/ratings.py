"""Team Elo ratings - the "honest baseline" model.

Not the full market-anchored/market-independent joint-distribution model the
original rebuild design deferred to an unwritten Plan 2 (see
docs/superpowers/specs/2026-08-20-fantasy-edge-nfl-rebuild-design.md in
homelab-master). This is deliberately a simple, transparent rating updated
after each final score, in the spirit already stated in
docs/nfl-modeling.md: a baseline predictor, not a claim of calibrated
probability. See src/services/elo.py for the update/probability math.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPrimaryKey, utcnow

STARTING_RATING = 1500.0


class TeamRating(Base, UUIDPrimaryKey):
    __tablename__ = "team_ratings"
    __table_args__ = (UniqueConstraint("team_id", name="uq_team_ratings_team_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized from teams.sport, same rationale as games.sport - every
    # /rankings/{sport} query filters directly rather than joining teams.
    sport: Mapped[str] = mapped_column(String(8), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=STARTING_RATING)
    # Running averages of points scored/allowed, updated the same place and
    # the same moment as `rating` (src/services/elo.py's
    # update_ratings_after_game) - the totals baseline (src/services/
    # totals.py) needs each team's own scoring level, which the win/loss-
    # only Elo rating does not encode. Null until games_played > 0 rather
    # than defaulting to 0.0, which would look like a real "shut out every
    # game" scoring level instead of "no data yet".
    avg_points_scored: Mapped[float | None] = mapped_column(Float)
    avg_points_allowed: Mapped[float | None] = mapped_column(Float)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
