from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
import redis

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus
from app.messaging.topics import STREAM_CRAWL_COMMANDS


@pytest.fixture()
def redis_db():
    client = redis.Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


def test_build_event_envelope_serializes_stable_fields():
    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id="job-123",
        payload={"pages": 3},
        source_service="test-suite",
        event_id="event-123",
        occurred_at="2026-05-06T12:00:00Z",
    )

    assert envelope.event_id == "event-123"
    assert envelope.event_type == "crawl.requested"
    assert envelope.aggregate_type == "crawl_job"
    assert envelope.aggregate_id == "job-123"
    assert envelope.source_service == "test-suite"
    assert envelope.schema_version == 1
    assert envelope.payload == {"pages": 3}
    assert envelope.occurred_at == "2026-05-06T12:00:00Z"

    serialized = envelope.to_dict()
    assert serialized["event_id"] == "event-123"
    assert serialized["schema_version"] == 1


def test_stream_bus_ensure_group_publish_consume_and_ack_round_trip(redis_db):
    bus = RedisStreamBus(redis_client=redis_db)
    stream_name = STREAM_CRAWL_COMMANDS
    group_name = f"group-{uuid.uuid4().hex}"
    consumer_name = f"consumer-{uuid.uuid4().hex}"

    bus.ensure_group(stream_name, group_name)
    bus.ensure_group(stream_name, group_name)

    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id="job-123",
        payload={"pages": 3},
        source_service="test-suite",
        event_id="event-456",
        occurred_at="2026-05-06T12:30:00Z",
    )

    message_id = bus.publish(stream_name, envelope)
    assert isinstance(message_id, str)

    messages = bus.consume_group(
        stream_name,
        group_name,
        consumer_name,
        count=10,
        block_ms=100,
    )

    assert len(messages) == 1
    assert messages[0].message_id == message_id
    assert messages[0].event.event_id == "event-456"
    assert messages[0].event.event_type == "crawl.requested"
    assert messages[0].event.payload == {"pages": 3}

    acked = bus.ack(stream_name, group_name, message_id)
    assert acked == 1

    assert bus.consume_group(stream_name, group_name, consumer_name, count=10, block_ms=100) == []


def test_stream_bus_rejects_unknown_topics(redis_db):
    bus = RedisStreamBus(redis_client=redis_db)
    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id="job-123",
        payload={"pages": 3},
    )

    with pytest.raises(ValueError, match="Unsupported stream topic"):
        bus.publish(f"stream.unknown.{uuid.uuid4().hex}", envelope)
