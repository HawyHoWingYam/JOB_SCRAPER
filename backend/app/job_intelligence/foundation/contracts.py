from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Generic, Protocol, TypeVar
from uuid import UUID

from app.job_intelligence.foundation.hashing import (
    json_payload,
    normalized_content_hash,
)
from app.utils.time import utc_now


_CONTENT_HASH = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class RevisionManifest:
    domain: str
    release_key: str
    content_hash: str
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("Revision domain is required")
        if not self.release_key.strip():
            raise ValueError("Revision release key is required")
        if not _CONTENT_HASH.fullmatch(self.content_hash):
            raise ValueError("Revision content hash must be lowercase SHA-256")

    @classmethod
    def from_content(
        cls,
        *,
        domain: str,
        release_key: str,
        content: Any,
        source_metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> RevisionManifest:
        return cls(
            domain=domain,
            release_key=release_key,
            content_hash=normalized_content_hash(content),
            source_metadata=dict(source_metadata or {}),
            created_at=created_at or utc_now(),
        )


@dataclass(frozen=True)
class RevisionRef:
    domain: str
    revision_id: UUID
    release_key: str
    content_hash: str

    def to_payload(self) -> dict[str, str]:
        return {
            "domain": self.domain,
            "revision_id": str(self.revision_id),
            "release_key": self.release_key,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class Provenance:
    method: str
    evidence_refs: tuple[Mapping[str, Any], ...]
    captured_at: datetime
    source_site: str | None = None
    source_revision: RevisionRef | None = None
    mapping_id: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not self.method.strip():
            raise ValueError("Provenance method is required")
        if self.captured_at.tzinfo is None:
            raise ValueError("Provenance capture time must include a timezone")

    def to_payload(self) -> dict[str, Any]:
        return json_payload(
            {
                "method": self.method,
                "source_site": self.source_site,
                "source_revision": (
                    self.source_revision.to_payload()
                    if self.source_revision is not None
                    else None
                ),
                "mapping_id": self.mapping_id,
                "evidence_refs": self.evidence_refs,
                "model_provider": self.model_provider,
                "model_name": self.model_name,
                "model_version": self.model_version,
                "captured_at": self.captured_at,
            }
        )


LOCAL_OPERATOR = "local-operator"


@dataclass(frozen=True)
class DecisionCommand:
    subject_id: str
    action: str
    expected_version: int
    idempotency_key: str
    confirmed: bool
    target_id: str | None = None
    actor: str = LOCAL_OPERATOR
    note: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("Decision subject ID is required")
        if not self.action.strip():
            raise ValueError("Decision action is required")
        if self.expected_version < 0:
            raise ValueError("Decision expected version cannot be negative")
        if not self.idempotency_key.strip():
            raise ValueError("Decision idempotency key is required")

    def to_payload(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "action": self.action,
            "target_id": self.target_id,
            "expected_version": self.expected_version,
            "idempotency_key": self.idempotency_key,
            "confirmed": self.confirmed,
            "actor": self.actor,
            "note": self.note,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class OutboxEvent:
    topic: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Mapping[str, Any]
    source_service: str = "job-intelligence-governance"


@dataclass(frozen=True)
class DecisionEffect:
    subject: Mapping[str, Any]
    resulting_projection: Mapping[str, Any] | None
    version: int
    evidence_refs: tuple[Mapping[str, Any], ...] = ()
    outbox_events: tuple[OutboxEvent, ...] = ()


@dataclass(frozen=True)
class DecisionResult:
    subject: Mapping[str, Any]
    resulting_projection: Mapping[str, Any] | None
    audit_event_id: UUID
    version: int
    replayed: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "subject": dict(self.subject),
            "resulting_projection": (
                dict(self.resulting_projection)
                if self.resulting_projection is not None
                else None
            ),
            "audit_event_id": str(self.audit_event_id),
            "version": self.version,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        replayed: bool,
    ) -> DecisionResult:
        projection = payload.get("resulting_projection")
        return cls(
            subject=dict(payload["subject"]),
            resulting_projection=(dict(projection) if projection is not None else None),
            audit_event_id=UUID(str(payload["audit_event_id"])),
            version=int(payload["version"]),
            replayed=replayed,
        )


SubjectT = TypeVar("SubjectT")


class DecisionTransition(Protocol, Generic[SubjectT]):
    """Domain-owned state transition invoked inside the foundation transaction."""

    domain: str
    subject_type: str

    def load_for_update(self, db: Any, subject_id: str) -> SubjectT | None:
        ...

    def version(self, subject: SubjectT) -> int:
        ...

    def snapshot(self, subject: SubjectT) -> Mapping[str, Any]:
        ...

    def apply(
        self,
        db: Any,
        subject: SubjectT,
        command: DecisionCommand,
    ) -> DecisionEffect:
        ...
