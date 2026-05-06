from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.utils.time import utc_now


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    source_service: str
    occurred_at: str
    schema_version: int
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_event_envelope(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    source_service: str = "outbox-publisher",
    event_id: str | None = None,
    occurred_at: str | datetime | None = None,
    schema_version: int = 1,
) -> EventEnvelope:
    if isinstance(occurred_at, datetime):
        occurred_at_value = occurred_at.isoformat()
    else:
        occurred_at_value = occurred_at or utc_now().isoformat()

    return EventEnvelope(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        source_service=source_service,
        occurred_at=occurred_at_value,
        schema_version=schema_version,
        payload=payload,
    )
