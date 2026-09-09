import logging

from sentinel.logging_config import configure_logging
from sentinel.observability import ObservabilityRegistry


def test_configure_logging_accepts_case_insensitive_level():
    configure_logging("debug")

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_falls_back_for_unknown_level():
    configure_logging("not-a-level")

    assert logging.getLogger().level == logging.INFO


def test_observability_registry_tracks_unknown_and_reconciliation_foundations():
    registry = ObservabilityRegistry()
    registry.record_unknown_transactions(2)
    registry.record_reconciliation_backlog(3)
    trace = registry.start_trace("trace-observe", transaction_id="txn-1")
    event = registry.log_event("transaction.unknown", transaction_id="txn-1", state="UNKNOWN")

    snapshot = registry.snapshot()

    assert snapshot.unknown_transactions == 2
    assert snapshot.reconciliation_backlog == 3
    assert trace.trace_id == "trace-observe"
    assert event["event"] == "transaction.unknown"
    assert "UNKNOWN" in snapshot.health_signals
    assert "RECONCILIATION_BACKLOG" in snapshot.alerts
