from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class OfferTodayTaxonomySnapshot(Base):
    """One successfully verified complete OfferToday classification tree."""

    __tablename__ = "offertoday_taxonomy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            name="uq_offertoday_taxonomy_snapshots_fingerprint",
        ),
        CheckConstraint(
            "source_site = 'offertoday' AND length(fingerprint) = 64",
            name="ck_offertoday_taxonomy_snapshots_identity",
        ),
        Index(
            "ix_offertoday_taxonomy_snapshots_verified",
            "verified_at",
            "id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False, default="offertoday")
    fingerprint = Column(String(64), nullable=False)
    catalog_payload = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=False, default=dict)
    verified_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class OfferTodayKeywordEntry(Base):
    """Ordinary-current keyword owned by one top-level classification."""

    __tablename__ = "offertoday_keyword_entries"
    __table_args__ = (
        UniqueConstraint(
            "source_classification_id",
            "normalized_keyword",
            name="uq_offertoday_keyword_entries_identity",
        ),
        CheckConstraint(
            "length(normalized_keyword) > 0 AND length(keyword) > 0",
            name="ck_offertoday_keyword_entries_keyword",
        ),
        CheckConstraint(
            "last_new_job_ids IS NULL OR last_new_job_ids >= 0",
            name="ck_offertoday_keyword_entries_new_ids",
        ),
        CheckConstraint(
            "last_duplicate_rate IS NULL OR "
            "(last_duplicate_rate >= 0 AND last_duplicate_rate <= 1)",
            name="ck_offertoday_keyword_entries_duplicate_rate",
        ),
        Index(
            "ix_offertoday_keyword_entries_pack",
            "source_classification_id",
            "enabled",
            "normalized_keyword",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_classification_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "source_classifications.id",
            name="fk_offertoday_keyword_entries_source_classification",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    keyword = Column(String(255), nullable=False)
    normalized_keyword = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=False, default="")
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    last_new_job_ids = Column(Integer, nullable=True)
    last_duplicate_rate = Column(Float, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    source_classification = relationship("SourceClassification")


class OfferTodayKeywordCsvReview(Base):
    """Expiring single-use authority for one validated CSV merge."""

    __tablename__ = "offertoday_keyword_csv_reviews"
    __table_args__ = (
        UniqueConstraint(
            "confirmation_token_hash",
            name="uq_offertoday_keyword_csv_reviews_token_hash",
        ),
        CheckConstraint(
            "length(confirmation_token_hash) = 64 "
            "AND length(csv_hash) = 64 "
            "AND length(catalog_fingerprint) = 64",
            name="ck_offertoday_keyword_csv_reviews_hashes",
        ),
        CheckConstraint(
            "expires_at > created_at AND "
            "(consumed_at IS NULL OR consumed_at >= created_at)",
            name="ck_offertoday_keyword_csv_reviews_lifecycle",
        ),
        Index(
            "ix_offertoday_keyword_csv_reviews_expiry",
            "expires_at",
            "consumed_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    confirmation_token_hash = Column(String(64), nullable=False)
    csv_hash = Column(String(64), nullable=False)
    catalog_fingerprint = Column(String(64), nullable=False)
    change_set = Column(JSON, nullable=False)
    diff = Column(JSON, nullable=False)
    resulting_enabled_counts = Column(JSON, nullable=False)
    workload_impact = Column(JSON, nullable=False)
    requested_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class OfferTodayKeywordMutationLog(Base):
    """Non-restorable audit summary for one confirmed keyword CSV merge."""

    __tablename__ = "offertoday_keyword_mutation_logs"
    __table_args__ = (
        CheckConstraint(
            "length(csv_hash) = 64 AND added_count >= 0 "
            "AND updated_count >= 0 AND disabled_count >= 0",
            name="ck_offertoday_keyword_mutation_logs_summary",
        ),
        Index("ix_offertoday_keyword_mutation_logs_created", "created_at", "id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor = Column(String(255), nullable=False)
    csv_hash = Column(String(64), nullable=False)
    added_count = Column(Integer, nullable=False)
    updated_count = Column(Integer, nullable=False)
    disabled_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


OFFERTODAY_COVERAGE_TABLES = (
    OfferTodayTaxonomySnapshot.__table__,
    OfferTodayKeywordEntry.__table__,
    OfferTodayKeywordCsvReview.__table__,
    OfferTodayKeywordMutationLog.__table__,
)


__all__ = [
    "OFFERTODAY_COVERAGE_TABLES",
    "OfferTodayKeywordCsvReview",
    "OfferTodayKeywordEntry",
    "OfferTodayKeywordMutationLog",
    "OfferTodayTaxonomySnapshot",
]
