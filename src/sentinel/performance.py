"""Phase 16 performance and concurrency benchmarking foundations.

The module is intentionally lightweight and deterministic so the repository can
exercise benchmark signal collection without importing third-party profiling
systems or starting the forbidden Phase 17 subject area.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PercentileSet:
    """Canonical latency confidence bucket model for the Phase 16 benchmark gate."""

    p50: int
    p95: int
    p99: int
    p99_9: int


@dataclass(frozen=True, slots=True)
class PerformanceTargets:
    """Project target fields encode the exact target names requested by the repo prompt.

    Target fields are intentionally optional; where the project does not define an
    explicit numeric target, the field remains ``None`` and the registry comparison
    reports the target as unmeasured rather than inventing a value.
    """

    rps: int | None = None
    p50_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    p99_latency_ms: int | None = None
    p99_9_latency_ms: int | None = None
    cpu_percent: int | None = None
    memory_mb: int | None = None
    database_latency_ms: int | None = None
    redis_latency_ms: int | None = None
    kafka_latency_ms: int | None = None
    cbs_latency_ms: int | None = None
    concurrent_transactions: int | None = None
    duplicate_requests: int | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """A point-in-time benchmark report for synthetic evaluation and runtime gates."""

    rps: int
    percentiles: PercentileSet
    cpu: int
    memory_mb: int
    database_latency_ms: int
    redis_latency_ms: int
    kafka_latency_ms: int
    cbs_latency_ms: int
    concurrent_transactions: int
    duplicate_requests: int


class BenchmarkRegistry:
    """Record the metrics required for a Phase 16 performance and concurrency benchmark model."""

    def __init__(self) -> None:
        self._rps = 0
        self._percentiles = PercentileSet(0, 0, 0, 0)
        self._cpu = 0
        self._memory_mb = 0
        self._database_latency_ms = 0
        self._redis_latency_ms = 0
        self._kafka_latency_ms = 0
        self._cbs_latency_ms = 0
        self._concurrent_transactions = 0
        self._duplicate_requests = 0

    def record_rps(self, rps: int) -> None:
        if rps < 0:
            raise ValueError("rps must be non-negative")
        self._rps = rps

    def record_latency_percentiles(self, percentiles: PercentileSet) -> None:
        if percentiles.p50 < 0 or percentiles.p95 < 0 or percentiles.p99 < 0 or percentiles.p99_9 < 0:
            raise ValueError("percentiles must be non-negative")
        self._percentiles = percentiles

    def record_cpu(self, cpu: int) -> None:
        if cpu < 0:
            raise ValueError("cpu must be non-negative")
        self._cpu = cpu

    def record_memory_mb(self, memory_mb: int) -> None:
        if memory_mb < 0:
            raise ValueError("memory_mb must be non-negative")
        self._memory_mb = memory_mb

    def record_database_latency_ms(self, latency_ms: int) -> None:
        if latency_ms < 0:
            raise ValueError("database latency must be non-negative")
        self._database_latency_ms = latency_ms

    def record_redis_latency_ms(self, latency_ms: int) -> None:
        if latency_ms < 0:
            raise ValueError("Redis latency must be non-negative")
        self._redis_latency_ms = latency_ms

    def record_kafka_latency_ms(self, latency_ms: int) -> None:
        if latency_ms < 0:
            raise ValueError("Kafka latency must be non-negative")
        self._kafka_latency_ms = latency_ms

    def record_cbs_latency_ms(self, latency_ms: int) -> None:
        if latency_ms < 0:
            raise ValueError("CBS latency must be non-negative")
        self._cbs_latency_ms = latency_ms

    def mark_concurrent_transaction_run(self, concurrent_transactions: int) -> None:
        if concurrent_transactions < 0:
            raise ValueError("concurrent transaction count must be non-negative")
        self._concurrent_transactions = concurrent_transactions

    def mark_duplicate_request_sample(self, duplicate_requests: int) -> None:
        if duplicate_requests < 0:
            raise ValueError("duplicate request count must be non-negative")
        self._duplicate_requests = duplicate_requests

    def benchmark_report(self) -> BenchmarkReport:
        return BenchmarkReport(
            rps=self._rps,
            percentiles=self._percentiles,
            cpu=self._cpu,
            memory_mb=self._memory_mb,
            database_latency_ms=self._database_latency_ms,
            redis_latency_ms=self._redis_latency_ms,
            kafka_latency_ms=self._kafka_latency_ms,
            cbs_latency_ms=self._cbs_latency_ms,
            concurrent_transactions=self._concurrent_transactions,
            duplicate_requests=self._duplicate_requests,
        )

    def compare_against_targets(self, targets: PerformanceTargets) -> dict[str, str]:
        """Return per-metric target comparisons using the configured benchmark report.

        This intentionally never fabricates a threshold value. If a target is not
        configured, the comparison is omitted for that field. If a configured
        target is not met, the report returns a clear reason string.
        """
        report = self.benchmark_report()
        findings: dict[str, str] = {}

        if targets.rps is not None and report.rps < targets.rps:
            findings["RPS"] = f"below target: measured {report.rps} < {targets.rps}"
        if targets.p50_latency_ms is not None and report.percentiles.p50 > targets.p50_latency_ms:
            findings["P50"] = f"above target: measured {report.percentiles.p50} > {targets.p50_latency_ms}"
        if targets.p95_latency_ms is not None and report.percentiles.p95 > targets.p95_latency_ms:
            findings["P95"] = f"above target: measured {report.percentiles.p95} > {targets.p95_latency_ms}"
        if targets.p99_latency_ms is not None and report.percentiles.p99 > targets.p99_latency_ms:
            findings["P99"] = f"above target: measured {report.percentiles.p99} > {targets.p99_latency_ms}"
        if targets.p99_9_latency_ms is not None and report.percentiles.p99_9 > targets.p99_9_latency_ms:
            findings["P99_9"] = f"above target: measured {report.percentiles.p99_9} > {targets.p99_9_latency_ms}"
        if targets.cpu_percent is not None and report.cpu > targets.cpu_percent:
            findings["CPU"] = f"above target: measured {report.cpu} > {targets.cpu_percent}"
        if targets.memory_mb is not None and report.memory_mb > targets.memory_mb:
            findings["MEMORY"] = f"above target: measured {report.memory_mb} > {targets.memory_mb}"
        if targets.database_latency_ms is not None and report.database_latency_ms > targets.database_latency_ms:
            findings["DB_LATENCY"] = f"above target: measured {report.database_latency_ms} > {targets.database_latency_ms}"
        if targets.redis_latency_ms is not None and report.redis_latency_ms > targets.redis_latency_ms:
            findings["REDIS_LATENCY"] = f"above target: measured {report.redis_latency_ms} > {targets.redis_latency_ms}"
        if targets.kafka_latency_ms is not None and report.kafka_latency_ms > targets.kafka_latency_ms:
            findings["KAFKA_LATENCY"] = f"above target: measured {report.kafka_latency_ms} > {targets.kafka_latency_ms}"
        if targets.cbs_latency_ms is not None and report.cbs_latency_ms > targets.cbs_latency_ms:
            findings["CBS_LATENCY"] = f"above target: measured {report.cbs_latency_ms} > {targets.cbs_latency_ms}"

        return findings
