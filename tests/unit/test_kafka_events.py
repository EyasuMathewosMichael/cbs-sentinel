import asyncio
import json
from datetime import UTC, datetime

import pytest
from aiokafka.errors import KafkaError

from sentinel.infrastructure.events import (
    EventEnvelope,
    EventSchemaError,
    InMemoryProcessedEventStore,
    KafkaEventConsumer,
    KafkaEventProducer,
)


class FakeProducer:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_and_wait(self, topic, **kwargs):
        self.calls.append((topic, kwargs))
        if len(self.calls) <= self.failures:
            raise KafkaError("temporary broker failure")


def make_event():
    return EventEnvelope.create(
        "transaction.received",
        "txn-1",
        "test-producer",
        {"state": "RECEIVED"},
        correlation_id="corr-1",
        trace_id="trace-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_event_envelope_round_trips_with_required_metadata():
    event = make_event()
    decoded = EventEnvelope.from_json(event.to_json())

    assert decoded == event
    assert decoded.schema_version == 1
    assert decoded.correlation_id == "corr-1"
    assert decoded.trace_id == "trace-1"
    assert decoded.sequence == 0


def test_event_schema_accepts_legacy_version_without_sequence():
    data = make_event().to_dict()
    data.pop("sequence")
    decoded = EventEnvelope.from_json(json.dumps(data))

    assert decoded.sequence == 0


def test_event_schema_rejects_naive_timestamp_and_non_json_payload():
    with pytest.raises(EventSchemaError):
        EventEnvelope.create(
            "transaction.received",
            "txn-1",
            "producer",
            {},
            timestamp=datetime(2026, 1, 1),
        )
    with pytest.raises(EventSchemaError):
        EventEnvelope.create("transaction.received", "txn-1", "producer", {"bad": object()})
    with pytest.raises(EventSchemaError, match="unsupported schema_version"):
        EventEnvelope.create("transaction.received", "txn-1", "producer", {}, schema_version=2)


def test_producer_retries_and_preserves_correlation_headers():
    broker = FakeProducer(failures=2)
    producer = KafkaEventProducer(
        broker,
        producer_name="test",
        max_attempts=3,
        retry_delay_seconds=0,
    )

    asyncio.run(producer.publish("transaction.received", make_event()))

    assert len(broker.calls) == 3
    topic, kwargs = broker.calls[-1]
    assert topic == "transaction.received"
    assert ("correlation_id", b"corr-1") in kwargs["headers"]
    assert ("trace_id", b"trace-1") in kwargs["headers"]


def test_consumer_is_idempotent_and_dead_letters_after_retries():
    broker = FakeProducer()
    dead_letters = KafkaEventProducer(broker, producer_name="consumer", retry_delay_seconds=0)
    processed = []

    async def handler(event):
        processed.append(event.event_id)

    consumer = KafkaEventConsumer(handler, InMemoryProcessedEventStore(), dead_letters)
    event = make_event()
    first = asyncio.run(consumer.process(event))
    duplicate = asyncio.run(consumer.process(event))

    assert first.status == "processed"
    assert duplicate.status == "duplicate"
    assert processed == [event.event_id]

    async def failing_handler(event):
        raise RuntimeError("handler failed")

    failing = KafkaEventConsumer(
        failing_handler,
        InMemoryProcessedEventStore(),
        dead_letters,
        max_attempts=2,
        handler_timeout_seconds=1,
    )
    result = asyncio.run(failing.process(event))

    assert result.status == "dead_lettered"
    assert result.attempts == 2
    assert broker.calls[-1][0] == "transaction.dead_letter"


def test_consumer_timeout_is_retried_and_dead_lettered():
    broker = FakeProducer()
    dead_letters = KafkaEventProducer(broker, producer_name="consumer", retry_delay_seconds=0)

    async def slow_handler(event):
        await asyncio.sleep(0.05)

    consumer = KafkaEventConsumer(
        slow_handler,
        InMemoryProcessedEventStore(),
        dead_letters,
        max_attempts=2,
        handler_timeout_seconds=0.001,
    )

    result = asyncio.run(consumer.process(make_event()))

    assert result.status == "dead_lettered"
    assert result.attempts == 2


def test_failed_event_can_be_replayed_and_out_of_order_events_are_rejected():
    broker = FakeProducer()
    dead_letters = KafkaEventProducer(broker, producer_name="consumer", retry_delay_seconds=0)
    calls = []
    should_fail = True

    async def handler(event):
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise RuntimeError("transient consumer failure")
        calls.append(event.event_id)

    store = InMemoryProcessedEventStore()
    consumer = KafkaEventConsumer(handler, store, dead_letters, max_attempts=1)
    event = EventEnvelope.create("transaction.received", "txn-1", "producer", {}, sequence=0)

    first = asyncio.run(consumer.process(event))
    replay = asyncio.run(consumer.process(event))
    stale = EventEnvelope.create("transaction.received", "txn-1", "producer", {}, sequence=2)
    stale_result = asyncio.run(consumer.process(stale))

    assert first.status == "dead_lettered"
    assert replay.status == "processed"
    assert stale_result.status == "stale"
    assert calls == [event.event_id]


def test_logically_duplicate_event_with_new_transport_id_is_rejected():
    broker = FakeProducer()
    dead_letters = KafkaEventProducer(broker, producer_name="consumer", retry_delay_seconds=0)
    calls = []

    async def handler(event):
        calls.append(event.event_id)

    consumer = KafkaEventConsumer(handler, InMemoryProcessedEventStore(), dead_letters)
    first = make_event()
    second = EventEnvelope.create(
        first.event_type,
        first.transaction_id,
        first.producer,
        first.payload,
        correlation_id=first.correlation_id,
        trace_id=first.trace_id,
        sequence=first.sequence,
        timestamp=first.timestamp,
    )

    assert asyncio.run(consumer.process(first)).status == "processed"
    assert asyncio.run(consumer.process(second)).status == "duplicate"
    assert calls == [first.event_id]