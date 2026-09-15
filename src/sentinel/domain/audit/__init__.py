"""Immutable, tamper-evident audit architecture."""

from sentinel.domain.audit.records import (
    AuditChainError,
    AuditEvent,
    AuditEventType,
    AuditRepository,
    DecisionAuditRecorder,
    InMemoryAuditRepository,
    SecurityEventAuditSink,
)

__all__ = [
    "AuditChainError",
    "AuditEvent",
    "AuditEventType",
    "DecisionAuditRecorder",
    "AuditRepository",
    "InMemoryAuditRepository",
    "SecurityEventAuditSink",
]