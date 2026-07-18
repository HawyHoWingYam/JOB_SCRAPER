from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.governance import GovernanceAuditEvent


@dataclass(frozen=True)
class AuditEvent:
    id: UUID
    domain: str
    subject_type: str
    subject_id: str
    action: str
    actor: str
    command_hash: str
    idempotency_key: str
    before_summary: Mapping[str, Any]
    after_summary: Mapping[str, Any]
    evidence_refs: tuple[Mapping[str, Any], ...]
    correlation_id: str
    created_at: datetime


@dataclass(frozen=True)
class AuditQuery:
    domain: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 200:
            raise ValueError("Governance audit page limit must be between 1 and 200")


@dataclass(frozen=True)
class AuditPage:
    items: tuple[AuditEvent, ...]
    next_cursor: str | None


def _encode_cursor(row: GovernanceAuditEvent) -> str:
    raw = json.dumps(
        {"created_at": row.created_at.isoformat(), "id": str(row.id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid governance audit cursor") from exc


class AuditReader:
    """Read immutable audit history using stable newest-first pagination."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _event(row: GovernanceAuditEvent) -> AuditEvent:
        return AuditEvent(
            id=row.id,
            domain=row.domain,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            action=row.action,
            actor=row.actor,
            command_hash=row.command_hash,
            idempotency_key=row.idempotency_key,
            before_summary=dict(row.before_summary),
            after_summary=dict(row.after_summary),
            evidence_refs=tuple(dict(item) for item in row.evidence_refs),
            correlation_id=row.correlation_id,
            created_at=row.created_at,
        )

    def list(self, query: AuditQuery) -> AuditPage:
        statement = self.db.query(GovernanceAuditEvent)
        if query.domain is not None:
            statement = statement.filter(GovernanceAuditEvent.domain == query.domain)
        if query.subject_type is not None:
            statement = statement.filter(
                GovernanceAuditEvent.subject_type == query.subject_type
            )
        if query.subject_id is not None:
            statement = statement.filter(
                GovernanceAuditEvent.subject_id == query.subject_id
            )
        if query.cursor is not None:
            created_at, event_id = _decode_cursor(query.cursor)
            statement = statement.filter(
                or_(
                    GovernanceAuditEvent.created_at < created_at,
                    and_(
                        GovernanceAuditEvent.created_at == created_at,
                        GovernanceAuditEvent.id < event_id,
                    ),
                )
            )
        rows = (
            statement.order_by(
                GovernanceAuditEvent.created_at.desc(),
                GovernanceAuditEvent.id.desc(),
            )
            .limit(query.limit + 1)
            .all()
        )
        page_rows = rows[: query.limit]
        return AuditPage(
            items=tuple(self._event(row) for row in page_rows),
            next_cursor=(
                _encode_cursor(page_rows[-1])
                if len(rows) > query.limit and page_rows
                else None
            ),
        )
