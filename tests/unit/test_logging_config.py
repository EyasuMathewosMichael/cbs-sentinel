import logging

from sentinel.logging_config import configure_logging
from sentinel.observability import ObservabilityRegistry
from sentinel.performance import BenchmarkRegistry, BenchmarkReport, PercentileSet


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


def test_phase_16_benchmark_registry_records_latency_percentiles_and_duplicate_concurrency_context():
    registry = BenchmarkRegistry()
    registry.record_rps(50)
    registry.record_latency_percentiles(PercentileSet(10, 25, 50, 90))
    registry.record_cpu(35)
    registry.record_memory_mb(128)
    registry.record_database_latency_ms(4)
    registry.record_redis_latency_ms(2)
    registry.record_kafka_latency_ms(8)
    registry.record_cbs_latency_ms(12)
    registry.mark_concurrent_transaction_run(8)
    registry.mark_duplicate_request_sample(2)

    report = registry.benchmark_report()

    assert report.rps == 50
    assert report.percentiles.p50 == 10
    assert report.percentiles.p95 == 25
    assert report.percentiles.p99 == 50
    assert report.percentiles.p99_9 == 90
    assert report.cpu == 35
    assert report.memory_mb == 128
    assert report.database_latency_ms == 4
    assert report.redis_latency_ms == 2
    assert report.kafka_latency_ms == 8
    assert report.cbs_latency_ms == 12
    assert report.concurrent_transactions == 8
    assert report.duplicate_requests == 2
