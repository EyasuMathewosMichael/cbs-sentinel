"""Transactional repositories for SENTINEL metadata and idempotency."""

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinel.domain.integrity import TransactionRequest
from sentinel.domain.transactions import Transaction
from sentinel.infrastructure.persistence.models import (
    IdempotencyRecord,
    TransactionRecord,
    TransactionStateRecord,
)


class IdempotencyConflictError(RuntimeError):
    """Raised when an identity is reused for a different request payload."""


class ConcurrentStateUpdateError(RuntimeError):
    """Raised when a state transition was based on stale persisted state."""


class IdempotencyRepository:
    """Durable idempotency reservation repository."""

    async def reserve(
        self,
        session: AsyncSession,
        request: TransactionRequest,
    ) -> bool:
        """Atomically reserve an identity; return false when already reserved."""
        fingerprint = _fingerprint(request)
        existing = await session.scalar(
            select(IdempotencyRecord).where(
                (IdempotencyRecord.idempotency_key == request.idempotency_key)
                | (IdempotencyRecord.transaction_id == request.transaction_id)
            )
        )
        if existing is not None:
            if existing.request_fingerprint == fingerprint:
                return False
            raise IdempotencyConflictError(
                f"request identity is already reserved: {request.idempotency_key}"
            )
        record = IdempotencyRecord(
            idempotency_key=request.idempotency_key,
            transaction_id=request.transaction_id,
            request_fingerprint=fingerprint,
        )
        try:
            async with session.begin_nested():
                session.add(record)
                await session.flush()
        except IntegrityError as error:
            existing = await session.scalar(
                select(IdempotencyRecord).where(
                    (IdempotencyRecord.idempotency_key == request.idempotency_key)
                    | (IdempotencyRecord.transaction_id == request.transaction_id)
                )
            )
            if existing is not None and existing.request_fingerprint == record.request_fingerprint:
                return False
            raise IdempotencyConflictError(
                f"request identity is already reserved: {request.idempotency_key}"
            ) from error
        return True


class TransactionRepository:
    """Repository for SENTINEL transaction metadata and append-only history."""

    async def create(
        self,
        session: AsyncSession,
        request: TransactionRequest,
        transaction: Transaction,
    ) -> TransactionRecord:
        """Persist metadata and the initial state history in one transaction."""
        record = TransactionRecord(
            transaction_id=request.transaction_id,
            request_id=request.transaction_id,
            idempotency_key=request.idempotency_key,
            source_account=request.source_account,
            destination_account=request.destination_account,
            amount=request.amount,
            currency=request.currency,
            transaction_type=request.transaction_type,
            state=transaction.state.value,
            state_history=[
                TransactionStateRecord(
                    previous_state=entry.previous_state.value if entry.previous_state else None,
                    new_state=entry.new_state.value,
                    actor=entry.actor,
                    occurred_at=entry.timestamp,
                )
                for entry in transaction.history
            ],
        )
        session.add(record)
        await session.flush()
        return record

    async def get(self, session: AsyncSession, transaction_id: str) -> TransactionRecord | None:
        """Load durable SENTINEL metadata by transaction identity."""
        result = await session.scalar(
            select(TransactionRecord)
            .options(selectinload(TransactionRecord.state_history))
            .where(TransactionRecord.transaction_id == transaction_id)
        )
        return result

    async def append_state(
        self,
        session: AsyncSession,
        transaction: Transaction,
        actor: str,
    ) -> None:
        """Persist the latest state and history entry in one database transaction."""
        record = await session.scalar(
            select(TransactionRecord)
            .where(TransactionRecord.transaction_id == transaction.transaction_id)
            .with_for_update()
        )
        if record is None:
            raise LookupError(f"unknown transaction: {transaction.transaction_id}")
        entry = transaction.history[-1]
        if entry.previous_state is None or record.state != entry.previous_state.value:
            raise ConcurrentStateUpdateError(
                f"stale state for transaction: {transaction.transaction_id}"
            )
        record.state = transaction.state.value
        session.add(
            TransactionStateRecord(
                transaction_id=transaction.transaction_id,
                previous_state=entry.previous_state.value if entry.previous_state else None,
                new_state=entry.new_state.value,
                actor=actor,
                occurred_at=entry.timestamp,
            )
        )
        await session.flush()


def _fingerprint(request: TransactionRequest) -> str:
    material = "|".join(
        (
            request.transaction_id,
            request.source_account,
            request.destination_account,
            str(request.amount),
            request.currency,
            request.transaction_type,
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()