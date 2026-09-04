from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, utcnow


class SleeperLeague(Base):
    __tablename__ = "sleeper_leagues"
    league_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Sleeper league IDs are unique platform-wide (no per-sport namespace),
    # so this isn't needed for identity - only for filtering/display once
    # more than one sport is synced (src/ingest/sleeper.py's SLEEPER_SPORTS).
    sport: Mapped[str] = mapped_column(String(8), nullable=False, default="nfl")
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    season: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    roster_positions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scoring_settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SleeperRoster(Base):
    __tablename__ = "sleeper_rosters"
    league_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    roster_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(32))
    starters: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    players: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SleeperLeagueSnapshot(Base):
    __tablename__ = "sleeper_league_snapshots"
    league_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    week: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    payload: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
