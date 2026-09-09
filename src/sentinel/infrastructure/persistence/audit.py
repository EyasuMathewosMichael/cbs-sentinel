"""Durable PostgreSQL repository for immutable audit events."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.domain.audit import AuditChainError, AuditEvent
from sentinel.infrastructure.persistence.models import AuditRecord


class AuditRecordRepository:
    """Append and verify tamper-evident audit records transactionally."""

    async def append(self, session: AsyncSession, event: AuditEvent) -> AuditEvent:
        event.verify()
        duplicate = await session.scalar(
            select(AuditRecord).where(
                (AuditRecord.event_id == event.event_id)
                | (AuditRecord.event_hash == event.event_hash)
            )
        )
        if duplicate is not None:
            raise AuditChainError("duplicate audit event identity")
        latest = await session.scalar(
            select(AuditRecord)
            .order_by(AuditRecord.occurred_at.desc(), AuditRecord.event_id.desc())
            .with_for_update()
        )
        expected_previous = latest.event_hash if latest else None
        if event.previous_hash != expected_previous:
            raise AuditChainError("audit event does not extend the durable chain")
        session.add(
            AuditRecord(
                event_id=event.event_id,
                event_type=event.event_type.value,
                occurred_at=event.occurred_at,
                actor=event.actor,
                why=event.why,
                action=event.action,
                what=event.what,
                transaction_id=event.transaction_id,
                correlation_id=event.correlation_id,
                policy=event.policy,
                rule=event.rule,
                model=event.model,
                payload=dict(event.payload),
                previous_hash=event.previous_hash,
                event_hash=event.event_hash,
            )
        )
        await session.flush()
        return event

    async def verify_chain(self, session: AsyncSession) -> None:
        records = (
            await session.scalars(
                select(AuditRecord).order_by(
                    AuditRecord.occurred_at, AuditRecord.event_id
                )
            )
        ).all()
        previous_hash: str | None = None
        for record in records:
            if record.previous_hash != previous_hash:
                raise AuditChainError("durable audit chain link mismatch")
            previous_hash = record.event_hash