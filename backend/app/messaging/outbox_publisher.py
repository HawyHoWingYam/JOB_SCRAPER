from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.messaging.event_envelope import build_event_envelope
from app.messaging.redis_stream_bus import RedisStreamBus
from app.repositories.event_outbox_repository import EventOutboxRepository


@dataclass(frozen=True)
class PublishBatchResult:
    selected_count: int
    published_count: int
    failed_count: int


class OutboxPublisher:
    """Publish pending outbox rows to Redis Streams."""

    def __init__(
        self,
        *,
        event_outbox_repository: EventOutboxRepository | None = None,
        stream_bus=None,
    ):
        self.event_outbox_repository = event_outbox_repository or EventOutboxRepository()
        self.stream_bus = stream_bus or RedisStreamBus()

    def publish_pending_batch(self, db: Session, *, limit: int = 100, now=None) -> PublishBatchResult:
        pending_rows = self.event_outbox_repository.list_pending(db, limit=limit, now=now)
        published_count = 0
        failed_count = 0

        for row in pending_rows:
            envelope = build_event_envelope(
                event_type=row.event_type,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                payload=row.payload,
                source_service=row.source_service,
                event_id=f"event-outbox:{row.id}",
                occurred_at=row.created_at,
            )
            try:
                self.stream_bus.publish(row.topic, envelope)
                self.event_outbox_repository.mark_published(db, row=row)
                published_count += 1
            except Exception as exc:
                self.event_outbox_repository.mark_retryable_failure(
                    db,
                    row=row,
                    error_message=str(exc),
                )
                failed_count += 1

        return PublishBatchResult(
            selected_count=len(pending_rows),
            published_count=published_count,
            failed_count=failed_count,
        )
