"""SQLAlchemy models for durable SENTINEL metadata, never bank ledger data."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base for SENTINEL persistence models."""


class TransactionRecord(Base):
    """Durable transaction metadata and current observed workflow state."""

    __tablename__ = "sentinel_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_sentinel_transactions_amount_positive"),
        Index("ix_sentinel_transactions_state", "state"),
        Index("ix_sentinel_transactions_created_at", "created_at"),
    )

    transaction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    source_account: Mapped[str] = mapped_column(String(256), nullable=False)
    destination_account: Mapped[str] = mapped_column(String(256), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    cbs_reference: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    state_history: Mapped[list[TransactionStateRecord]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class TransactionStateRecord(Base):
    """Append-only state transition history for a transaction."""

    __tablename__ = "sentinel_transaction_state_history"
    __table_args__ = (
        Index("ix_sentinel_state_history_transaction", "transaction_id", "occurred_at"),
    )

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("sentinel_transactions.transaction_id", ondelete="CASCADE"), nullable=False
    )
    previous_state: Mapped[str | None] = mapped_column(String(64))
    new_state: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    transaction: Mapped[TransactionRecord] = relationship(back_populates="state_history")


class IdempotencyRecord(Base):
    """Durable request identity preventing duplicate SENTINEL effects."""

    __tablename__ = "sentinel_idempotency_records"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_sentinel_idempotency_transaction"),
        Index("ix_sentinel_idempotency_expires_at", "expires_at"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    response_status: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
