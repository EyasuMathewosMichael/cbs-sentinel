"""Stable, JSON-compatible Kafka event envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

CURRENT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({CURRENT_SCHEMA_VERSION})


class EventSchemaError(ValueError):
    """Raised when an event does not satisfy the versioned envelope contract."""


class EventTopic(StrEnum):
    """Approved Phase 10 topics; reconciliation remains a later phase."""

    RECEIVED = "transaction.received"
    ACCEPTED = "transaction.accepted"
    SUBMITTED = "transaction.submitted"
    POSTED = "transaction.posted"
    FAILED = "transaction.failed"
    TIMEOUT = "transaction.timeout"
    UNKNOWN = "transaction.unknown"
    ANOMALY = "transaction.anomaly"
    RISK = "transaction.risk"
    PROTECTIVE_ACTION = "transaction.protective_action"
    AUDIT = "transaction.audit"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Transport envelope; delivery is at-least-once, never financial truth."""

    event_id: str
    event_type: str
    transaction_id: str
    timestamp: datetime
    producer: str
    schema_version: int
    correlation_id: str
    trace_id: str
    sequence: int
    payload: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        event_type: str,
        transaction_id: str,
        producer: str,
        payload: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        timestamp: datetime | None = None,
        schema_version: int = CURRENT_SCHEMA_VERSION,
        sequence: int = 0,
    ) -> EventEnvelope:
        envelope = cls(
            event_id=str(uuid4()),
            event_type=event_type,
            transaction_id=transaction_id,
            timestamp=timestamp or datetime.now(UTC),
            producer=producer,
            schema_version=schema_version,
            correlation_id=correlation_id or str(uuid4()),
            trace_id=trace_id or str(uuid4()),
            sequence=sequence,
            payload=dict(payload),
        )
        envelope.validate()
        return envelope

    def validate(self) -> None:
        for name in (
            "event_id",
            "event_type",
            "transaction_id",
            "producer",
            "correlation_id",
            "trace_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise EventSchemaError(f"{name} must be a non-empty string")
        if self.timestamp.tzinfo is None:
            raise EventSchemaError("timestamp must be timezone-aware")
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise EventSchemaError(f"unsupported schema_version: {self.schema_version}")
        if self.sequence < 0:
            raise EventSchemaError("sequence must not be negative")
        try:
            json.dumps(self.payload)
        except (TypeError, ValueError) as error:
            raise EventSchemaError("payload must be JSON serializable") from error

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "producer": self.producer,
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "payload": dict(self.payload),
        }

    def to_json(self) -> bytes:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True).encode()

    @classmethod
    def from_json(cls, value: bytes | str) -> EventEnvelope:
        try:
            data = json.loads(value)
            timestamp = datetime.fromisoformat(data["timestamp"])
            envelope = cls(
                event_id=data["event_id"],
                event_type=data["event_type"],
                transaction_id=data["transaction_id"],
                timestamp=timestamp,
                producer=data["producer"],
                schema_version=data["schema_version"],
                correlation_id=data["correlation_id"],
                trace_id=data["trace_id"],
                sequence=data.get("sequence", 0),
                payload=data["payload"],
            )
            envelope.validate()
            return envelope
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise EventSchemaError("invalid event envelope") from error