"""Personal singles ledger. Placement terms and audit events are append-only."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base, UUIDPrimaryKey, CreatedAt
import uuid


class LedgerBet(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = 'ledger_bets'
    __table_args__ = (CheckConstraint('stake > 0', name='ledger_positive_stake'),)
    request_id: Mapped[str] = mapped_column(String(80), unique=True)
    mode: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    stake: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('games.id', ondelete='RESTRICT'), index=True)
    terms: Mapped[dict] = mapped_column(JSONB)


class LedgerEvent(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = 'ledger_events'
    request_id: Mapped[str] = mapped_column(String(80), unique=True)
    bet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('ledger_bets.id', ondelete='RESTRICT'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSONB)


class LedgerPolicy(Base, UUIDPrimaryKey, CreatedAt):
    __tablename__ = 'ledger_policies'
    currency: Mapped[str] = mapped_column(String(3))
    limits: Mapped[dict] = mapped_column(JSONB)
