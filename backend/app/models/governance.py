from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.utils.time import utc_now


class GovernanceRevision(Base):
    """Immutable published identity shared by governed domain revisions."""

    __tablename__ = "governance_revisions"
    __table_args__ = (
        UniqueConstraint(
            "domain",
            "release_key",
            name="uq_governance_revision_release_key",
        ),
        UniqueConstraint(
            "domain",
            "content_hash",
            name="uq_governance_revision_content_hash",
        ),
        CheckConstraint(
            "status = 'published'",
            name="ck_governance_revision_published",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_revision_content_hash",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String(100), nullable=False, index=True)
    release_key = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_metadata = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="published")
    created_at = Column(DateTime(timezone=True), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class GovernanceAuditEvent(Base):
    """Append-only record of one trusted-local governance decision."""

    __tablename__ = "governance_audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor = 'local-operator'",
            name="ck_governance_audit_actor_local_operator",
        ),
        CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_audit_command_hash",
        ),
        Index(
            "ix_governance_audit_domain_created_id",
            "domain",
            "created_at",
            "id",
        ),
        Index(
            "ix_governance_audit_subject_created",
            "subject_type",
            "subject_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String(100), nullable=False)
    subject_type = Column(String(100), nullable=False)
    subject_id = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    actor = Column(String(255), nullable=False)
    command_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    before_summary = Column(JSON, nullable=False)
    after_summary = Column(JSON, nullable=False)
    evidence_refs = Column(JSON, nullable=False, default=list)
    correlation_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class GovernanceIdempotencyRecord(Base):
    """Serialized first result for one domain-scoped decision command key."""

    __tablename__ = "governance_idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "domain",
            "idempotency_key",
            name="uq_governance_idempotency_domain_key",
        ),
        CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_idempotency_command_hash",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=False)
    command_hash = Column(String(64), nullable=False)
    audit_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    result_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


@event.listens_for(GovernanceRevision, "before_update")
def _prevent_governance_revision_update(_mapper, _connection, _revision) -> None:
    raise ValueError("Governance revisions are immutable")


@event.listens_for(GovernanceRevision, "before_delete")
def _prevent_governance_revision_delete(_mapper, _connection, _revision) -> None:
    raise ValueError("Governance revisions are immutable")


@event.listens_for(GovernanceAuditEvent, "before_update")
def _prevent_governance_audit_update(_mapper, _connection, _event) -> None:
    raise ValueError("Governance audit events are append-only")


@event.listens_for(GovernanceAuditEvent, "before_delete")
def _prevent_governance_audit_delete(_mapper, _connection, _event) -> None:
    raise ValueError("Governance audit events are append-only")


@event.listens_for(GovernanceIdempotencyRecord, "before_update")
def _prevent_governance_idempotency_update(_mapper, _connection, _record) -> None:
    raise ValueError("Governance idempotency records are immutable")


@event.listens_for(GovernanceIdempotencyRecord, "before_delete")
def _prevent_governance_idempotency_delete(_mapper, _connection, _record) -> None:
    raise ValueError("Governance idempotency records are immutable")


GOVERNANCE_FOUNDATION_TABLES = (
    GovernanceRevision.__table__,
    GovernanceAuditEvent.__table__,
    GovernanceIdempotencyRecord.__table__,
)
