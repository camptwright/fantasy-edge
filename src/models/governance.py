"""Model artifacts, their predictions, and ingestion audit.

passed_gate is how the spec's calibration decision is enforced in code rather
than by discipline: the serving process refuses to load an artifact where it
is false. ingestion_runs lets data freshness be reported independently of
model health - they are separate questions and conflating them makes an
exhausted odds quota look like an uncalibrated model.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAt, UUIDPrimaryKey, utcnow


class ModelArtifact(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = "model_artifacts"

    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # anchored|independent
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    seasons_used: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)

    brier: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    passed_gate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ModelPrediction(Base, UUIDPrimaryKey):
    __tablename__ = "model_predictions"

    artifact_version: Mapped[str] = mapped_column(String(64), nullable=False)
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    line: Mapped[float | None] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IngestionRun(Base, UUIDPrimaryKey):
    __tablename__ = "ingestion_runs"

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
