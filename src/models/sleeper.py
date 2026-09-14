from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, utcnow


class SleeperLeague(Base):
    __tablename__ = "sleeper_leagues"
    # Despite the table/model name, this also holds ESPN Fantasy leagues as
    # of src/ingest/espn_fantasy.py (see alembic/versions/0014) - kept
    # rather than renamed to avoid touching every consumer in
    # src/api/main.py, which only ever treats league_id as an opaque
    # string. ESPN rows use "espn:<numeric league id>" so the two
    # platforms' independent id spaces can never collide with each other.
    league_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="sleeper")
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
    # 40, not 32: Sleeper's owner_id is a short numeric snowflake, but
    # ESPN's is a dash-stripped SWID UUID (36 chars) - confirmed live
    # 2026-09-09, a real sync failed with StringDataRightTruncationError
    # against the original String(32) column the moment a real ESPN
    # league was synced.
    owner_id: Mapped[str | None] = mapped_column(String(40))
    # Best-effort display name for the trade recommender (src/services/
    # trade.py) - neither platform's roster object carries this itself.
    # Sleeper: GET /league/{id}/users' metadata.team_name (fallback
    # display_name), fetched separately in src/ingest/sleeper.py. ESPN:
    # team.name, already present in the same mRoster response
    # src/ingest/espn_fantasy.py already fetches. Nullable/best-effort -
    # every existing consumer of this table only ever needed owner_id,
    # so a sync that can't resolve a name must not become a hard failure.
    team_name: Mapped[str | None] = mapped_column(String(160))
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
