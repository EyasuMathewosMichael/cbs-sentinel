from datetime import UTC, datetime

import pytest

from sentinel.domain.audit import (
    AuditChainError,
    AuditEvent,
    AuditEventType,
    DecisionAuditRecorder,
    InMemoryAuditRepository,
    SecurityEventAuditSink,
)


def event(previous_hash=None):
    return AuditEvent.create(
        AuditEventType.ADMINISTRATIVE_ACTION,
        actor="security-admin",
        why="approve administrative action",
        action="approve",
        payload={"action": "approve"},
        transaction_id="txn-audit",
        correlation_id="corr-audit",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        previous_hash=previous_hash,
    )


def test_audit_chain_appends_and_verifies():
    repository = InMemoryAuditRepository()
    first = repository.append(event())
    second = repository.append(event(first.event_hash))

    repository.verify_chain()
    assert len(repository.events()) == 2
    assert second.previous_hash == first.event_hash


def test_audit_chain_rejects_wrong_link_and_tampering():
    repository = InMemoryAuditRepository()
    first = repository.append(event())
    with pytest.raises(AuditChainError):
        repository.append(event("wrong-hash"))

    object.__setattr__(first, "actor", "tampered")
    with pytest.raises(AuditChainError):
        repository.verify_chain()


def test_audit_chain_rejects_duplicate_event_identity():
    repository = InMemoryAuditRepository()
    first = repository.append(event())
    duplicate = AuditEvent(
        first.event_id,
        first.event_type,
        first.occurred_at,
        first.actor,
        first.why,
        first.action,
        first.what,
        first.transaction_id,
        first.correlation_id,
        first.policy,
        first.rule,
        first.model,
        first.payload,
        first.previous_hash,
        first.event_hash,
    )

    with pytest.raises(AuditChainError, match="duplicate"):
        repository.append(duplicate)


def test_audit_event_requires_aware_time_and_actor():
    with pytest.raises(ValueError):
        AuditEvent.create(
            AuditEventType.SECURITY_ACTION,
            actor=" ",
            why="reason",
            action="action",
            payload={},
            occurred_at=datetime(2026, 1, 1),
        )


def test_security_events_are_converted_to_auditable_chain_records():
    repository = InMemoryAuditRepository()
    sink = SecurityEventAuditSink(repository)
    sink.record(
        type(
            "Event",
            (),
            {
                "event_type": "break_glass_requested",
                "subject": "operator",
                "request_id": "bg-1",
            },
        )()
    )

    repository.verify_chain()
    record = repository.events()[0]
    assert record.event_type is AuditEventType.SECURITY_ACTION
    assert record.actor == "operator"


def test_decision_recorder_captures_all_completeness_dimensions():
    repository = InMemoryAuditRepository()
    recorder = DecisionAuditRecorder(repository)
    record = recorder.record_decision(
        AuditEventType.RISK_DECISION,
        actor="risk-engine",
        why="amount threshold exceeded",
        action="hold",
        transaction_id="txn-complete",
        correlation_id="corr-complete",
        policy="risk-policy-v1",
        rule="amount-threshold",
        model="rules-v1",
        payload={"score": 80},
    )

    assert record.actor == "risk-engine"
    assert record.why == "amount threshold exceeded"
    assert record.action == "hold"
    assert record.transaction_id == "txn-complete"
    assert record.policy == "risk-policy-v1"
    assert record.rule == "amount-threshold"
    assert record.model == "rules-v1"
    repository.verify_chain()


def test_audit_event_emits_explicit_semantic_dimension_fields():
    event = AuditEvent.create(
        AuditEventType.RISK_DECISION,
        actor="risk-engine",
        why="amount threshold exceeded",
        action="hold",
        transaction_id="txn-complete",
        correlation_id="corr-complete",
        policy="risk-policy-v1",
        rule="amount-threshold",
        model="rules-v1",
        payload={"score": 80},
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert event.event_type is AuditEventType.RISK_DECISION
    assert event.what == event.event_type.value
    assert event.actor == "risk-engine"
    assert event.why == "amount threshold exceeded"
    assert event.action == "hold"
    assert event.transaction_id == "txn-complete"
    assert event.correlation_id == "corr-complete"
    assert event.policy == "risk-policy-v1"
    assert event.rule == "amount-threshold"
    assert event.model == "rules-v1"
    assert event.payload == {"score": 80}
    assert event.occurred_at.tzinfo is not None