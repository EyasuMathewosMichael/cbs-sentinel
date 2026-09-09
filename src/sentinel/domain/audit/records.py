"""Canonical immutable audit records with tamper-evident hash chaining."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from threading import Lock
from typing import Protocol
from uuid import uuid4


class AuditChainError(RuntimeError):
    """Raised when an audit chain is appended or verified incorrectly."""


class AuditEventType(StrEnum):
    TRANSACTION_RECEIVED = "transaction.received"
    TRANSACTION_STATE_CHANGED = "transaction.state_changed"
    INTEGRITY_DECISION = "transaction.integrity_decision"
    RISK_DECISION = "transaction.risk_decision"
    PROTECTIVE_DECISION = "transaction.protective_decision"
    RECONCILIATION_DECISION = "transaction.reconciliation_decision"
    RECOVERY_ACTION = "transaction.recovery_action"
    ADMINISTRATIVE_ACTION = "administrative.action"
    SECURITY_ACTION = "security.action"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable event whose hash commits to the preceding event."""

    event_id: str
    event_type: AuditEventType
    occurred_at: datetime
    actor: str
    why: str
    action: str
    what: str
    transaction_id: str | None
    correlation_id: str | None
    policy: str | None
    rule: str | None
    model: str | None
    payload: Mapping[str, object]
    previous_hash: str | None
    event_hash: str

    @classmethod
    def create(
        cls,
        event_type: AuditEventType,
        *,
        actor: str,
        why: str,
        action: str,
        payload: Mapping[str, object],
        transaction_id: str | None = None,
        correlation_id: str | None = None,
        policy: str | None = None,
        rule: str | None = None,
        model: str | None = None,
        what: str | None = None,
        occurred_at: datetime | None = None,
        previous_hash: str | None = None,
    ) -> AuditEvent:
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not actor.strip() or not why.strip() or not action.strip():
            raise ValueError("actor, why, and action must not be empty")
        event_id = str(uuid4())
        semantic_what = what or event_type.value
        canonical = _canonical(
            event_id,
            event_type,
            timestamp,
            actor,
            why,
            action,
            semantic_what,
            transaction_id,
            correlation_id,
            policy,
            rule,
            model,
            payload,
            previous_hash,
        )
        return cls(
            event_id,
            event_type,
            timestamp,
            actor,
            why,
            action,
            semantic_what,
            transaction_id,
            correlation_id,
            policy,
            rule,
            model,
            dict(payload),
            previous_hash,
            sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def verify(self) -> None:
        expected = sha256(
            _canonical(
                self.event_id,
                self.event_type,
                self.occurred_at,
                self.actor,
                self.why,
                self.action,
                self.what,
                self.transaction_id,
                self.correlation_id,
                self.policy,
                self.rule,
                self.model,
                self.payload,
                self.previous_hash,
            ).encode("utf-8")
        ).hexdigest()
        if expected != self.event_hash:
            raise AuditChainError(f"audit event hash mismatch: {self.event_id}")


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> AuditEvent: ...

    def events(self) -> tuple[AuditEvent, ...]: ...

    def verify_chain(self) -> None: ...


class InMemoryAuditRepository:
    """Thread-safe development repository; production uses the same contract durably."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = Lock()

    def append(self, event: AuditEvent) -> AuditEvent:
        event.verify()
        with self._lock:
            if any(
                existing.event_id == event.event_id or existing.event_hash == event.event_hash
                for existing in self._events
            ):
                raise AuditChainError("duplicate audit event identity")
            previous_hash = self._events[-1].event_hash if self._events else None
            if event.previous_hash != previous_hash:
                raise AuditChainError("audit event does not extend the current chain")
            self._events.append(event)
            return event

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def verify_chain(self) -> None:
        with self._lock:
            previous_hash: str | None = None
            for event in self._events:
                event.verify()
                if event.previous_hash != previous_hash:
                    raise AuditChainError("audit chain link mismatch")
                previous_hash = event.event_hash


class SecurityEventAuditSink:
    """Adapt Phase 13 security events into immutable Phase 14 audit events."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    def record(self, event: object) -> None:
        event_type = getattr(event, "event_type", "security.action")
        subject = getattr(event, "subject", "unknown")
        request_id = getattr(event, "request_id", None)
        previous = self._repository.events()[-1].event_hash if self._repository.events() else None
        self._repository.append(
            AuditEvent.create(
                AuditEventType.SECURITY_ACTION,
                actor=subject,
                why=f"security event: {event_type}",
                action=event_type,
                what=event_type,
                transaction_id=request_id,
                payload={"event_type": event_type},
                previous_hash=previous,
            )
        )


class DecisionAuditRecorder:
    """Record critical transaction and administrative decisions through the audit chain."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    def record_decision(
        self,
        event_type: AuditEventType,
        *,
        actor: str,
        why: str,
        action: str,
        transaction_id: str | None = None,
        correlation_id: str | None = None,
        policy: str | None = None,
        rule: str | None = None,
        model: str | None = None,
        what: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        previous = self._repository.events()[-1].event_hash if self._repository.events() else None
        event = AuditEvent.create(
            event_type,
            actor=actor,
            why=why,
            action=action,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            policy=policy,
            rule=rule,
            model=model,
            what=what,
            payload=payload or {},
            previous_hash=previous,
        )
        return self._repository.append(event)


def _canonical(
    event_id: str,
    event_type: AuditEventType,
    occurred_at: datetime,
    actor: str,
    why: str,
    action: str,
    what: str,
    transaction_id: str | None,
    correlation_id: str | None,
    policy: str | None,
    rule: str | None,
    model: str | None,
    payload: Mapping[str, object],
    previous_hash: str | None,
) -> str:
    return json.dumps(
        {
            "actor": actor,
            "correlation_id": correlation_id,
            "event_id": event_id,
            "event_type": event_type.value,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "why": why,
            "action": action,
            "what": what,
            "payload": payload,
            "policy": policy,
            "previous_hash": previous_hash,
            "rule": rule,
            "model": model,
            "transaction_id": transaction_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )