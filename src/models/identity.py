"""Canonical identity for teams and players.

Player identity is the highest-risk element of this schema. nflverse keys on
gsis_id, ESPN on its own numerics, Underdog on UUIDs, and Underdog's line
payload carries no team (constraint #17), so a player cannot be disambiguated
by roster from that response alone.

Name matching is unsafe: two active players are named Josh Allen - a
Jacksonville edge rusher and the Buffalo quarterback. A naive name join
attributes one player's props to the other's statistics and raises nothing.
PlayerExternalId is therefore a real table with per-source uniqueness.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAt, UUIDPrimaryKey


class Team(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "teams"

    espn_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    nflverse_abbr: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class Player(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "players"

    gsis_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[str | None] = mapped_column(String(8))
    current_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )


class PlayerExternalId(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "player_external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_player_external_source_id"),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
