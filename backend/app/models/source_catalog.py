from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.utils.time import utc_now


class SourceCatalogCandidate(Base):
    """Immutable discovered payload awaiting validation and publication."""

    __tablename__ = "source_catalog_candidates"
    __table_args__ = (
        Index(
            "ux_source_catalog_candidates_active_fingerprint",
            "source_site",
            "fingerprint",
            unique=True,
            postgresql_where=text("state <> 'superseded'"),
            sqlite_where=text("state <> 'superseded'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False, index=True)
    base_revision_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=False)
    normalized_payload = Column(JSON, nullable=False)
    source_payload = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False, default=dict)
    diff = Column(JSON, nullable=False, default=dict)
    validation_summary = Column(JSON, nullable=False, default=dict)
    state = Column(String(32), nullable=False, default="discovered", index=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class SourceCatalogValidationRun(Base):
    """One durable offline or bounded live-smoke validation attempt."""

    __tablename__ = "source_catalog_validation_runs"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "validation_kind",
            "expected_target_hash",
            "attempt",
            name="uq_source_catalog_validation_attempt",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    validation_kind = Column(String(32), nullable=False, index=True)
    node_key = Column(String(255), nullable=True)
    classification_id = Column(String(255), nullable=True)
    expected_target_hash = Column(String(64), nullable=False, default="catalog")
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempt = Column(Integer, nullable=False, default=1)
    claimed_by = Column(String(255), nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    error = Column(JSON, nullable=True)
    manual_action = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SourceCatalogRevision(Base):
    """Immutable validated Source Taxonomy snapshot."""

    __tablename__ = "source_catalog_revisions"
    __table_args__ = (
        UniqueConstraint("source_site", "sequence", name="uq_source_catalog_revision_sequence"),
        UniqueConstraint("source_site", "fingerprint", name="uq_source_catalog_revision_fingerprint"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    normalized_payload = Column(JSON, nullable=False)
    source_payload = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False, default=dict)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_candidates.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    predecessor_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    publication_metadata = Column(JSON, nullable=False, default=dict)
    published_by = Column(String(255), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceCatalogActiveRevision(Base):
    """The one executable revision pointer for a Source."""

    __tablename__ = "source_catalog_active_revisions"

    source_site = Column(String(32), primary_key=True)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    updated_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceCatalogChangeReview(Base):
    """Expiring single-use approval bound to one catalog pointer change."""

    __tablename__ = "source_catalog_change_reviews"
    __table_args__ = (
        CheckConstraint("operation IN ('publish', 'rollback')", name="ck_source_catalog_review_operation"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash = Column(String(64), nullable=False, unique=True)
    operation = Column(String(16), nullable=False, index=True)
    source_site = Column(String(32), nullable=False, index=True)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    candidate_fingerprint = Column(String(64), nullable=True)
    base_active_revision_id = Column(UUID(as_uuid=True), nullable=True)
    automation_impact_digest = Column(String(64), nullable=False)
    automation_impact = Column(JSON, nullable=False, default=dict)
    actor = Column(String(255), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceCatalogPublication(Base):
    """Append-only history of publish and rollback pointer changes."""

    __tablename__ = "source_catalog_publications"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('publish', 'rollback')",
            name="ck_source_catalog_publication_operation",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False, index=True)
    operation = Column(String(16), nullable=False)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_revision_id = Column(UUID(as_uuid=True), nullable=True)
    candidate_id = Column(UUID(as_uuid=True), nullable=True)
    review_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_catalog_change_reviews.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    actor = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


SOURCE_CATALOG_TABLES = (
    SourceCatalogCandidate.__table__,
    SourceCatalogValidationRun.__table__,
    SourceCatalogRevision.__table__,
    SourceCatalogActiveRevision.__table__,
    SourceCatalogChangeReview.__table__,
    SourceCatalogPublication.__table__,
)


_IMMUTABLE_CANDIDATE_FIELDS = (
    "source_site",
    "base_revision_id",
    "fingerprint",
    "normalized_payload",
    "source_payload",
    "provenance",
    "diff",
)


@event.listens_for(SourceCatalogCandidate, "before_update")
def _prevent_candidate_payload_update(_mapper, _connection, candidate) -> None:
    state = inspect(candidate)
    if any(state.attrs[field].history.has_changes() for field in _IMMUTABLE_CANDIDATE_FIELDS):
        raise ValueError("Source Catalog candidate payload is immutable")


@event.listens_for(SourceCatalogRevision, "before_update")
def _prevent_revision_update(_mapper, _connection, _revision) -> None:
    raise ValueError("Source Catalog revisions are immutable")


@event.listens_for(SourceCatalogRevision, "before_delete")
def _prevent_revision_delete(_mapper, _connection, _revision) -> None:
    raise ValueError("Source Catalog revisions are immutable")
