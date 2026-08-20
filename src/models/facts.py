"""Observed facts: fixtures, realized statistics, and market lines.

SIGN CONVENTION - read this before writing to team_market_lines.

`line` is ALWAYS that side's handicap as a sportsbook would print it:
negative means the side gives points, positive means it receives them. Home
favoured by 3 is stored as home = -3.0, away = +3.0.

This matters because the sources disagree and neither raises an error:

  nflverse  spread_line = +3    means the HOME team is favoured by 3
  ESPN      spread      = +1.5  means the home team is the UNDERDOG by 1.5

Verified live 2026-08-20 against an ESPN scoreboard event with details
'LV -1.5', away team LV, and homeTeamOdds.favorite = False. The two feeds are
exact mirrors of one another, so writing either raw into this column mixes
opposite conventions in one field and silently corrupts every model trained
on it. Each ingester converts to the convention above; tests assert it.

Both line tables are APPEND-ONLY. Line movement history is the only record of
what the market did, and closing-line value is by definition a comparison
between the line at bet time and the eventual close. Never UPDATE or DELETE
an observation row.

player_game_stats is stored LONG - (player, game, stat_type, value) - rather
than one column per statistic. The central query in this application joins
offered lines to realized outcomes on (player_id, game_id, stat_type), which
is a direct join in long form and needs a statistic-to-column mapping layer
in wide form. That layer is exactly where constraint #8's normalization drift
reappears.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAt, UUIDPrimaryKey, utcnow


class Game(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "games"
    __table_args__ = (Index("ix_games_season_week", "season", "week"),)

    nflverse_game_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    espn_event_id: Mapped[str | None] = mapped_column(String(32), unique=True)

    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int | None] = mapped_column(Integer)
    game_type: Mapped[str | None] = mapped_column(String(8))

    # CONSTRAINT #2: nullable on purpose - providers publish fixtures before a
    # kickoff time exists. Any WHERE on this column must use
    # or_(Game.game_time.is_(None), ...) or those rows silently vanish.
    game_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    home_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT")
    )
    away_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT")
    )

    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", nullable=False)

    home_rest: Mapped[int | None] = mapped_column(Integer)
    away_rest: Mapped[int | None] = mapped_column(Integer)
    div_game: Mapped[bool | None] = mapped_column(Boolean)
    roof: Mapped[str | None] = mapped_column(String(16))
    surface: Mapped[str | None] = mapped_column(String(24))
    temp: Mapped[float | None] = mapped_column(Float)
    wind: Mapped[float | None] = mapped_column(Float)


class TeamMarketLine(Base, UUIDPrimaryKey):
    __tablename__ = "team_market_lines"
    __table_args__ = (
        Index(
            "ix_team_lines_latest",
            "game_id",
            "market",
            "side",
            "source",
            "observed_at",
        ),
    )

    # RESTRICT, not CASCADE: this table is append-only observation history
    # (see module docstring). Cascading a Game delete would silently destroy
    # that history instead of leaving the decision explicit.
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    market: Mapped[str] = mapped_column(String(16), nullable=False)  # spread|total|moneyline
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # home|away|over|under
    line: Mapped[float | None] = mapped_column(Float)  # null for moneyline
    price_american: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    line_type: Mapped[str] = mapped_column(String(8), nullable=False)  # opening|live|closing
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PlayerPropLine(Base, UUIDPrimaryKey):
    __tablename__ = "player_prop_lines"
    __table_args__ = (
        Index(
            "ix_prop_lines_latest",
            "player_id",
            "stat_type",
            "source",
            "observed_at",
        ),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="SET NULL")
    )
    stat_type: Mapped[str] = mapped_column(String(48), nullable=False)
    line: Mapped[float] = mapped_column(Float, nullable=False)
    over_price_american: Mapped[int | None] = mapped_column(Integer)
    under_price_american: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PlayerGameStat(Base, UUIDPrimaryKey):
    __tablename__ = "player_game_stats"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "game_id", "stat_type", name="uq_player_game_stat"
        ),
    )

    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT, not CASCADE: this is the realized ground-truth training data
    # the model fits against. Cascading a Game delete would silently destroy
    # it instead of leaving the decision explicit.
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    stat_type: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
