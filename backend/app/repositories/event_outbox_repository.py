from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.event_outbox import EventOutbox
from app.utils.time import utc_now


class EventOutboxRepository:
    """Repository for durable publish-later events."""

    def enqueue(
        self,
        db: Session,
        *,
        topic: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        source_service: str = "outbox-publisher",
        available_at: datetime | None = None,
        auto_commit: bool = True,
    ) -> EventOutbox:
        row = EventOutbox(
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            source_service=source_service,
            payload=payload,
            available_at=available_at or utc_now(),
        )
        db.add(row)
        if auto_commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row

    def list_pending(
        self,
        db: Session,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[EventOutbox]:
        reference_time = now or utc_now()
        return (
            db.query(EventOutbox)
            .filter(
                EventOutbox.status == "pending",
                EventOutbox.available_at <= reference_time,
            )
            .order_by(EventOutbox.id.asc())
            .limit(limit)
            .all()
        )

    def mark_published(
        self,
        db: Session,
        *,
        row: EventOutbox,
        published_at: datetime | None = None,
        auto_commit: bool = True,
    ) -> EventOutbox:
        row.status = "published"
        row.published_at = published_at or utc_now()
        row.last_error = None
        if auto_commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row

    def mark_retryable_failure(
        self,
        db: Session,
        *,
        row: EventOutbox,
        error_message: str,
        now: datetime | None = None,
        auto_commit: bool = True,
    ) -> EventOutbox:
        row.status = "pending"
        row.attempt_count += 1
        row.last_error = error_message
        delay_seconds = min(5 * (2 ** (row.attempt_count - 1)), 300)
        row.available_at = (now or utc_now()) + timedelta(seconds=delay_seconds)
        if auto_commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row
