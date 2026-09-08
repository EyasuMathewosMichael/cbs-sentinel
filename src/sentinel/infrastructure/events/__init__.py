"""Versioned Kafka event architecture for asynchronous, at-least-once delivery."""

from sentinel.infrastructure.events.consumer import (
    ConsumerResult,
    InMemoryProcessedEventStore,
    KafkaEventConsumer,
)
from sentinel.infrastructure.events.producer import (
    KafkaEventProducer,
    KafkaEventPublisher,
    KafkaPublishError,
    create_kafka_producer,
)
from sentinel.infrastructure.events.schema import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    EventEnvelope,
    EventSchemaError,
    EventTopic,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ConsumerResult",
    "EventEnvelope",
    "EventSchemaError",
    "EventTopic",
    "SUPPORTED_SCHEMA_VERSIONS",
    "InMemoryProcessedEventStore",
    "KafkaEventConsumer",
    "KafkaEventProducer",
    "KafkaEventPublisher",
    "KafkaPublishError",
    "create_kafka_producer",
]