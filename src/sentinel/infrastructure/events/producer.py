"""Kafka producers with bounded retry and orchestration-compatible publishing."""

from __future__ import annotations

import asyncio
from typing import Any

from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]
from aiokafka.errors import KafkaError  # type: ignore[import-untyped]

from sentinel.domain.transactions import Transaction
from sentinel.infrastructure.events.schema import EventEnvelope


class KafkaPublishError(RuntimeError):
    """Raised after bounded producer retries are exhausted."""


class KafkaEventProducer:
    """Publish versioned envelopes with at-least-once retry semantics."""

    def __init__(
        self,
        producer: Any,
        *,
        producer_name: str,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        if max_attempts < 1 or retry_delay_seconds < 0:
            raise ValueError("producer retry settings are invalid")
        self._producer = producer
        self._producer_name = producer_name
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, event: EventEnvelope) -> None:
        event.validate()
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                await self._producer.send_and_wait(
                    topic,
                    key=event.transaction_id.encode(),
                    value=event.to_json(),
                    headers=[
                        ("event_id", event.event_id.encode()),
                        ("correlation_id", event.correlation_id.encode()),
                        ("trace_id", event.trace_id.encode()),
                        ("schema_version", str(event.schema_version).encode()),
                    ],
                )
                return
            except (KafkaError, TimeoutError, OSError) as error:
                last_error = error
                if attempt + 1 < self._max_attempts:
                    await asyncio.sleep(self._retry_delay_seconds * (2**attempt))
        raise KafkaPublishError(
            f"failed to publish event {event.event_id} after {self._max_attempts} attempts"
        ) from last_error


def create_kafka_producer(bootstrap_servers: str, **kwargs: Any) -> KafkaEventProducer:
    """Create a production aiokafka producer with durable acknowledgement settings."""
    if not bootstrap_servers.strip():
        raise ValueError("bootstrap_servers must not be empty")
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        **kwargs,
    )
    return KafkaEventProducer(producer, producer_name="sentinel")


class KafkaEventPublisher:
    """Adapter for the existing orchestration EventHook protocol."""

    def __init__(self, producer: KafkaEventProducer, *, producer_name: str = "sentinel") -> None:
        self._producer = producer
        self._producer_name = producer_name

    async def publish(self, event_type: str, transaction: Transaction) -> None:
        event = EventEnvelope.create(
            event_type,
            transaction.transaction_id,
            self._producer_name,
            {"state": transaction.state.value},
            correlation_id=transaction.transaction_id,
            sequence=len(transaction.history) - 1,
        )
        await self._producer.publish(event_type, event)