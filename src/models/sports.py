"""Sports-specific persistence that is intentionally separate from legacy Fantasy rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.orm import Base, _created_at, _pk


class ProviderSource(Base):
    __tablename__ = "sports_provider_sources"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    permission_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="review")
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class ProviderExternalID(Base):
    __tablename__ = "sports_provider_external_ids"

    id: Mapped[uuid.UUID] = _pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sports_provider_sources.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("provider_id", "entity_type", "external_id", name="uq_sports_provider_entity"),)


class EventParticipant(Base):
    __tablename__ = "sports_event_participants"

    id: Mapped[uuid.UUID] = _pk()
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"))
    player_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(24), nullable=False)

    __table_args__ = (Index("ix_sports_event_participant_event", "event_id"),)


class TeamIdentityCrosswalk(Base):
    __tablename__ = "sports_team_identity_crosswalks"

    id: Mapped[uuid.UUID] = _pk()
    sport: Mapped[str] = mapped_column(String(32), nullable=False)
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("sport", "league", "provider", "external_id", name="uq_sports_team_crosswalk"),)


class MarketAssessment(Base):
    __tablename__ = "sports_market_assessments"

    id: Mapped[uuid.UUID] = _pk()
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True)
    sport: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    league: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[str] = mapped_column(String(48), nullable=False)
    selection: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status_reason: Mapped[str | None] = mapped_column(String(256))
    probability: Mapped[float | None] = mapped_column(Float)
    fair_price_american: Mapped[int | None] = mapped_column(Integer)
    edge_percent: Mapped[float | None] = mapped_column(Float)
    estimated_value_percent: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(64))
    source_snapshot_ids: Mapped[list | None] = mapped_column(JSON)
    assessed_at: Mapped[datetime] = _created_at()


class Favorite(Base):
    __tablename__ = "sports_favorites"

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sport: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("kind", "canonical_id", name="uq_sports_favorite"),)


class PaperPosition(Base):
    __tablename__ = "sports_paper_positions"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sports_market_assessments.id", ondelete="RESTRICT"), nullable=False)
    assumed_price_american: Mapped[int] = mapped_column(Integer, nullable=False)
    stake_units: Mapped[float] = mapped_column(Float, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    opened_at: Mapped[datetime] = _created_at()

