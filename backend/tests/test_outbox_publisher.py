from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.messaging.topics import STREAM_CRAWL_COMMANDS
from app.models import EventOutbox
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.redis_stream_bus import RedisStreamBus


@pytest.fixture()
def redis_db():
    client = redis.Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture()
def sqlite_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[EventOutbox.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_publish_pending_batch_marks_row_published_after_stream_write(sqlite_session, redis_db):
    repository = EventOutboxRepository()
    bus = RedisStreamBus(redis_client=redis_db)
    publisher = OutboxPublisher(event_outbox_repository=repository, stream_bus=bus)

    stream_name = STREAM_CRAWL_COMMANDS
    row = repository.enqueue(
        sqlite_session,
        topic=stream_name,
        aggregate_type="crawl_job",
        aggregate_id=str(uuid.uuid4()),
        event_type="crawl.requested",
        payload={"pages": 3},
    )

    result = publisher.publish_pending_batch(sqlite_session, limit=10)

    sqlite_session.refresh(row)
    assert result.selected_count == 1
    assert result.published_count == 1
    assert result.failed_count == 0
    assert row.status == "published"
    assert row.published_at is not None
    assert redis_db.xlen(stream_name) == 1


def test_publish_pending_batch_retries_and_retains_pending_state_on_failure(sqlite_session, redis_db):
    repository = EventOutboxRepository()

    class FailingBus:
        def publish(self, topic, envelope):
            raise RuntimeError("redis unavailable")

    publisher = OutboxPublisher(event_outbox_repository=repository, stream_bus=FailingBus())

    row = repository.enqueue(
        sqlite_session,
        topic=STREAM_CRAWL_COMMANDS,
        aggregate_type="crawl_job",
        aggregate_id=str(uuid.uuid4()),
        event_type="crawl.requested",
        payload={"pages": 3},
    )
    original_available_at = row.available_at

    result = publisher.publish_pending_batch(sqlite_session, limit=10)

    sqlite_session.refresh(row)
    assert result.selected_count == 1
    assert result.published_count == 0
    assert result.failed_count == 1
    assert row.status == "pending"
    assert row.attempt_count == 1
    assert row.last_error == "redis unavailable"
    assert row.available_at > original_available_at


def test_publish_pending_batch_preserves_source_service_from_outbox_row(sqlite_session, redis_db):
    repository = EventOutboxRepository()
    bus = RedisStreamBus(redis_client=redis_db)
    publisher = OutboxPublisher(event_outbox_repository=repository, stream_bus=bus)

    row = repository.enqueue(
        sqlite_session,
        topic=STREAM_CRAWL_COMMANDS,
        aggregate_type="job",
        aggregate_id=str(uuid.uuid4()),
        event_type="job.ingested",
        payload={"job_id": "abc"},
        source_service="ingest-worker",
    )

    result = publisher.publish_pending_batch(sqlite_session, limit=10)

    assert result.published_count == 1
    message_id, values = redis_db.xrange(STREAM_CRAWL_COMMANDS, count=1)[0]
    assert isinstance(message_id, str)
    payload = json.loads(values["data"])
    assert payload["source_service"] == "ingest-worker"
    sqlite_session.refresh(row)
    assert row.status == "published"
