from __future__ import annotations

from datetime import datetime
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
        available_at: datetime | None = None,
        auto_commit: bool = True,
    ) -> EventOutbox:
        row = EventOutbox(
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
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
