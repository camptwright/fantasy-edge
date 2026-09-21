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
    # RESTRICT, not CASCADE: a recorded prediction is part of the model's
    # audit trail. Cascading a Game delete would silently destroy it instead
    # of leaving the decision explicit.
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
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


class ResultSyncState(Base):
    """Durable, per-game retry cursor; a successful fetch is not permanent."""
    __tablename__ = 'result_sync_states'
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('games.id', ondelete='RESTRICT'), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)


class ResultCorrection(Base, UUIDPrimaryKey):
    """Two-fetch confirmation ledger. Applied/superseded entries are retained."""
    __tablename__ = 'result_corrections'
    stat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('player_game_stats.id', ondelete='RESTRICT'), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[float] = mapped_column(Float, nullable=False)
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    first_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RecommendationSnapshot(Base, UUIDPrimaryKey):
    """Append-only deterministic summaries, bound to quote IDs and generation time.

    Serving rechecks actionability and regenerates each quote's numeric text
    before returning a cached summary. Legacy LLM narratives are withheld.
    """
    quote_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(36)), nullable=True)

    __tablename__ = "recommendation_snapshots"

    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CalibrationReport(Base, UUIDPrimaryKey):
    """One walk-forward backtest run (src/services/backtest.py) for one
    sport/market pair - deliberately its own table, not a repurposing of
    ModelArtifact. ModelArtifact's artifact_path/kind/trained_at describe a
    trained, serialized model file; the Elo/totals baseline is neither
    trained nor serialized, so populating those columns for it would mean
    inventing placeholder values - exactly the fabrication this
    application's "honest baseline" ethos exists to avoid. Append-only like
    every other observation table here: each run is kept, not upserted,
    so passed_gate history is auditable over time as more games accumulate.
    """

    __tablename__ = "calibration_reports"

    sport: Mapped[str] = mapped_column(String(8), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False)  # moneyline|spread|total
    seasons_used: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    brier_score: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    # True when brier_score beats the flat-50% reference point (0.25) by a
    # meaningful margin - see scripts/run_calibration.py for the actual
    # threshold and rationale. False, not null, when sample_size is too
    # small to trust: an untrusted report must never look identical to a
    # report that hasn't run yet.
    passed_gate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
