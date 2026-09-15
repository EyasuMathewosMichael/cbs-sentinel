"""Enterprise observability foundations for SENTINEL.

The implementation deliberately stays lightweight and repository-native:
- a metrics registry for operational signals,
- structured event logging,
- trace context objects,
- dashboard signal definitions,
- health signal classification,
- alert foundation hooks for unknown transactions and reconciliation backlog.

The telemetry model is intentionally deterministic and analyzable in-memory so
that later phases can connect it to Prometheus, OpenTelemetry, Grafana, log
aggregation, and Kafka/Redis/Postgres diagnostics without changing the core
project contract.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("sentinel.observability")

SENSITIVE_LOG_FIELDS = {
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "key",
    "ssn",
    "iban",
    "account_number",
    "routing_number",
}


@dataclass(frozen=True, slots=True)
class TraceContext:
    """A lightweight in-memory trace context for request and event correlation."""

    trace_id: str
    transaction_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ObservabilitySnapshot:
    """A point-in-time observability readout for the enterprise control plane."""

    unknown_transactions: int
    reconciliation_backlog: int
    health_signals: tuple[str, ...]
    alerts: tuple[str, ...]
    metrics: dict[str, int]
    traces: tuple[TraceContext, ...]
    logs: tuple[dict[str, Any], ...]
    throughput: int = 0
    latency_ms: int = 0
    p95_latency_ms: int = 0
    p99_latency_ms: int = 0
    cbs_latency_ms: int = 0
    failures: int = 0
    kafka_lag: int = 0
    database_latency_ms: int = 0
    redis_failures: int = 0
    circuit_breaker_count: int = 0
    circuit_breaker_states: tuple[str, ...] = ()


class ObservabilityRegistry:
    """Own the deterministic observability foundations required by Phase 15.

    It is intentionally repository-friendly: it does not require Redis, Kafka,
    OpenTelemetry, Prometheus, or a full Grafana deployment, but it provides the
    contract points and data objects a production observability stack can build on.
    """

    def __init__(self) -> None:
        self._unknown_transactions = 0
        self._reconciliation_backlog = 0
        self._metrics: Counter[str] = Counter()
        self._traces: list[TraceContext] = []
        self._logs: list[dict[str, Any]] = []
        self._throughput = 0
        self._latency_ms = 0
        self._p95_latency_ms = 0
        self._p99_latency_ms = 0
        self._cbs_latency_ms = 0
        self._failures = 0
        self._kafka_lag = 0
        self._database_latency_ms = 0
        self._redis_failures = 0
        self._circuit_breaker_states: list[str] = []

    def record_throughput(self, count: int) -> None:
        """Record throughput events per selected sampling interval."""
        if count < 0:
            raise ValueError("throughput must be non-negative")
        self._throughput = count
        self._metrics["THROUGHPUT"] = count

    def record_latency_ms(self, latency_ms: int) -> None:
        """Record observed end-to-end latency in milliseconds."""
        if latency_ms < 0:
            raise ValueError("latency must be non-negative")
        self._latency_ms = latency_ms
        self._metrics["LATENCY_MS"] = latency_ms

    def record_p95_latency_ms(self, latency_ms: int) -> None:
        """Record the p95 latency bucket for latency review dashboards."""
        if latency_ms < 0:
            raise ValueError("p95 latency must be non-negative")
        self._p95_latency_ms = latency_ms
        self._metrics["P95_LATENCY_MS"] = latency_ms

    def record_p99_latency_ms(self, latency_ms: int) -> None:
        """Record the p99 latency bucket for reliability review dashboards."""
        if latency_ms < 0:
            raise ValueError("p99 latency must be non-negative")
        self._p99_latency_ms = latency_ms
        self._metrics["P99_LATENCY_MS"] = latency_ms

    def record_cbs_latency_ms(self, latency_ms: int) -> None:
        """Record authoritative CBS boundary latency in milliseconds."""
        if latency_ms < 0:
            raise ValueError("CBS latency must be non-negative")
        self._cbs_latency_ms = latency_ms
        self._metrics["CBS_LATENCY_MS"] = latency_ms

    def record_failures(self, count: int) -> None:
        """Record observed failure count for the sampled interval."""
        if count < 0:
            raise ValueError("failure count must be non-negative")
        self._failures = count
        self._metrics["FAILURES"] = count

    def record_unknown_transactions(self, count: int) -> None:
        """Record the authoritative number of UNKNOWN transactions awaiting resolution."""
        if count < 0:
            raise ValueError("unknown transaction count must be non-negative")
        self._unknown_transactions = count
        self._metrics["UNKNOWN_TRANSACTIONS"] = count

    def record_reconciliation_backlog(self, count: int) -> None:
        """Record the number of transactions requiring reconciliation investigation."""
        if count < 0:
            raise ValueError("reconciliation backlog count must be non-negative")
        self._reconciliation_backlog = count
        self._metrics["RECONCILIATION_BACKLOG"] = count

    def record_kafka_lag(self, lag: int) -> None:
        """Record observed Kafka event lag for consumer health."""
        if lag < 0:
            raise ValueError("Kafka lag must be non-negative")
        self._kafka_lag = lag
        self._metrics["KAFKA_LAG"] = lag

    def record_database_latency_ms(self, latency_ms: int) -> None:
        """Record an observed PostgreSQL or durable metadata-store latency sample."""
        if latency_ms < 0:
            raise ValueError("database latency must be non-negative")
        self._database_latency_ms = latency_ms
        self._metrics["DATABASE_LATENCY_MS"] = latency_ms

    def record_redis_failures(self, count: int) -> None:
        """Record Redis coordination failures seen in a sampled interval."""
        if count < 0:
            raise ValueError("Redis failure count must be non-negative")
        self._redis_failures = count
        self._metrics["REDIS_FAILURES"] = count

    def register_circuit_breaker(self, name: str, state: str) -> None:
        """Register a circuit-breaker signal with a canonical state string."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("circuit breaker name must not be empty")
        if not isinstance(state, str) or not state.strip():
            raise ValueError("circuit breaker state must not be empty")
        self._circuit_breaker_states.append(f"{name}:{state.upper()}")
        self._metrics["CIRCUIT_BREAKERS"] = len(self._circuit_breaker_states)

    def start_trace(self, trace_id: str, *, transaction_id: str | None = None) -> TraceContext:
        """Start a trace context and store it for later inspection."""
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id must not be empty")
        trace = TraceContext(trace_id=trace_id, transaction_id=transaction_id)
        self._traces.append(trace)
        return trace

    def log_event(self, event: str, **fields: Any) -> dict[str, Any]:
        """Emit a structured log event and return the canonical event record.

        Sensitive fields, including passwords, tokens, secrets, authorization
        headers, and account-identifying information, are redacted before the
        structured log record is stored and emitted.
        """
        if not isinstance(event, str) or not event.strip():
            raise ValueError("event name must not be empty")

        clean = self._redact(fields)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "trace_id": clean.get("trace_id"),
            "transaction_id": clean.get("transaction_id"),
            "state": clean.get("state"),
        }
        # allow an event payload to carry any extra structured key-value pairs
        for key, value in clean.items():
            if key not in record:
                record[key] = value
        self._logs.append(record)
        logger.info("event=%s structured=%s", event, record)
        return record

    def append_metric(self, name: str, value: int) -> None:
        """Store a metric under a stable key and include it in the dashboard model."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric name must not be empty")
        if value < 0:
            raise ValueError("metric value must be non-negative")
        self._metrics[name] = value

    def dashboard_definitions(self) -> tuple[str, ...]:
        """Return the names of the dashboard panels that the observability foundation supports."""
        return (
            "THROUGHPUT",
            "LATENCY",
            "P95_P99_LATENCY",
            "CBS_LATENCY",
            "FAILURES",
            "UNKNOWN_TRANSACTIONS",
            "RECONCILIATION_BACKLOG",
            "KAFKA_LAG",
            "DATABASE_LATENCY",
            "REDIS_FAILURES",
            "CIRCUIT_BREAKERS",
        )

    def snapshot(self) -> ObservabilitySnapshot:
        """Return immutable observability facts suitable for tests and operational snapshots."""
        health_signals = []
        if self._unknown_transactions > 0:
            health_signals.append("UNKNOWN")
        else:
            health_signals.append("NO_UNKNOWN")

        if self._reconciliation_backlog > 0:
            health_signals.append("RECONCILIATION_BACKLOG")
        else:
            health_signals.append("RECONCILIATION_CLEAR")

        if self._kafka_lag > 0:
            health_signals.append("KAFKA_LAG")
        if self._redis_failures > 0:
            health_signals.append("REDIS_FAILURES")
        if self._failures > 0:
            health_signals.append("FAILURES")

        alerts = []
        if self._unknown_transactions > 0:
            alerts.append("UNKNOWN")
        if self._reconciliation_backlog > 0:
            alerts.append("RECONCILIATION_BACKLOG")
        if self._kafka_lag > 0:
            alerts.append("KAFKA_LAG")
        if self._redis_failures > 0:
            alerts.append("REDIS_FAILURES")
        if self._failures > 0:
            alerts.append("FAILURES")

        return ObservabilitySnapshot(
            unknown_transactions=self._unknown_transactions,
            reconciliation_backlog=self._reconciliation_backlog,
            health_signals=tuple(health_signals),
            alerts=tuple(alerts),
            metrics=dict(self._metrics),
            traces=tuple(self._traces),
            logs=tuple(self._logs),
            throughput=self._throughput,
            latency_ms=self._latency_ms,
            p95_latency_ms=self._p95_latency_ms,
            p99_latency_ms=self._p99_latency_ms,
            cbs_latency_ms=self._cbs_latency_ms,
            failures=self._failures,
            kafka_lag=self._kafka_lag,
            database_latency_ms=self._database_latency_ms,
            redis_failures=self._redis_failures,
            circuit_breaker_count=len(self._circuit_breaker_states),
            circuit_breaker_states=tuple(self._circuit_breaker_states),
        )

    def _redact(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Return a structured dictionary whose sensitive fields are masked."""
        clean: dict[str, Any] = {}
        for key, value in fields.items():
            name = str(key).lower()
            if name in SENSITIVE_LOG_FIELDS:
                clean[key] = "[REDACTED]"
            elif isinstance(value, dict):
                clean[key] = {
                    k: "[REDACTED]" if str(k).lower() in SENSITIVE_LOG_FIELDS else v
                    for k, v in value.items()
                }
            else:
                clean[key] = value
        return clean
