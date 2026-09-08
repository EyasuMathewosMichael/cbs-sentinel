"""Idempotent Kafka event processing with bounded retries and dead letters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from sentinel.infrastructure.events.producer import KafkaEventProducer
from sentinel.infrastructure.events.schema import EventEnvelope


class EventHandler(Protocol):
    async def __call__(self, event: EventEnvelope) -> None: ...


class ProcessedEventStore(Protocol):
    async def begin(self, event: EventEnvelope) -> str: ...

    async def complete(self, event: EventEnvelope) -> None: ...

    async def release(self, event: EventEnvelope) -> None: ...


class InMemoryProcessedEventStore:
    """Test/development deduplication store; production may use durable storage."""

    def __init__(self) -> None:
        self._completed: set[tuple[str, str, int]] = set()
        self._in_flight: set[tuple[str, str, int]] = set()
        self._next_sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def begin(self, event: EventEnvelope) -> str:
        key = _processing_key(event)
        async with self._lock:
            if key in self._completed or key in self._in_flight:
                return "duplicate"
            expected = self._next_sequences.get(event.transaction_id, 0)
            if event.sequence != expected:
                return "stale"
            self._in_flight.add(key)
            return "accepted"

    async def complete(self, event: EventEnvelope) -> None:
        key = _processing_key(event)
        async with self._lock:
            self._in_flight.discard(key)
            self._completed.add(key)
            self._next_sequences[event.transaction_id] = event.sequence + 1

    async def release(self, event: EventEnvelope) -> None:
        key = _processing_key(event)
        async with self._lock:
            self._in_flight.discard(key)


@dataclass(frozen=True, slots=True)
class ConsumerResult:
    status: str
    attempts: int


class KafkaEventConsumer:
    """Process at-least-once deliveries without repeating a claimed event."""

    def __init__(
        self,
        handler: EventHandler,
        processed_events: ProcessedEventStore,
        dead_letter_producer: KafkaEventProducer,
        *,
        dead_letter_topic: str = "transaction.dead_letter",
        max_attempts: int = 3,
        handler_timeout_seconds: float = 5,
    ) -> None:
        if max_attempts < 1 or handler_timeout_seconds <= 0:
            raise ValueError("consumer retry settings are invalid")
        self._handler = handler
        self._processed_events = processed_events
        self._dead_letter_producer = dead_letter_producer
        self._dead_letter_topic = dead_letter_topic
        self._max_attempts = max_attempts
        self._handler_timeout_seconds = handler_timeout_seconds

    async def process(self, event: EventEnvelope) -> ConsumerResult:
        event.validate()
        admission = await self._processed_events.begin(event)
        if admission != "accepted":
            return ConsumerResult(admission, 0)
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                await asyncio.wait_for(self._handler(event), self._handler_timeout_seconds)
                await self._processed_events.complete(event)
                return ConsumerResult("processed", attempt)
            except Exception as error:
                last_error = error
                if attempt < self._max_attempts:
                    await asyncio.sleep(0)
        await self._processed_events.release(event)
        dead_letter = EventEnvelope.create(
            "transaction.dead_letter",
            event.transaction_id,
            "sentinel.consumer",
            {
                "original_event": event.to_dict(),
                "error": str(last_error),
                "attempts": self._max_attempts,
            },
            correlation_id=event.correlation_id,
            trace_id=event.trace_id,
        )
        await self._dead_letter_producer.publish(self._dead_letter_topic, dead_letter)
        return ConsumerResult("dead_lettered", self._max_attempts)


def _processing_key(event: EventEnvelope) -> tuple[str, str, int]:
    """Identify one logical transaction event independent of transport event ID."""
    return event.transaction_id, event.event_type, event.sequence