from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.utils.time import utc_now


class CanonicalJobTaxonomyRelease(Base):
    __tablename__ = "canonical_job_taxonomy_releases"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "content_hash",
            name="uq_canonical_job_taxonomy_release_hash",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_taxonomy_release_hash",
        ),
        CheckConstraint(
            "expected_domain_count >= 0 AND expected_category_count >= 0 "
            "AND expected_subcategory_count >= 0",
            name="ck_canonical_job_taxonomy_release_expected_counts",
        ),
        CheckConstraint(
            "materialized_domain_count >= 0 AND materialized_category_count >= 0 "
            "AND materialized_subcategory_count >= 0",
            name="ck_canonical_job_taxonomy_release_materialized_counts",
        ),
        CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_canonical_job_taxonomy_release_status",
        ),
        CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_domain_count = materialized_domain_count "
            "AND expected_category_count = materialized_category_count "
            "AND expected_subcategory_count = materialized_subcategory_count)",
            name="ck_canonical_job_taxonomy_release_ready",
        ),
    )

    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    content_hash = Column(String(64), nullable=False)
    expected_domain_count = Column(Integer, nullable=False)
    expected_category_count = Column(Integer, nullable=False)
    expected_subcategory_count = Column(Integer, nullable=False)
    materialized_domain_count = Column(Integer, nullable=False, default=0)
    materialized_category_count = Column(Integer, nullable=False, default=0)
    materialized_subcategory_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="materializing")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    ready_at = Column(DateTime(timezone=True), nullable=True)


class CanonicalJobTaxonomyActiveRevision(Base):
    __tablename__ = "canonical_job_taxonomy_active_revisions"
    __table_args__ = (
        CheckConstraint(
            "singleton_key = 'canonical-job-taxonomy'",
            name="ck_canonical_job_taxonomy_active_singleton",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_canonical_job_taxonomy_active_version",
        ),
        ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "canonical_job_taxonomy_releases.revision_id",
                "canonical_job_taxonomy_releases.content_hash",
            ],
            name="fk_canonical_job_taxonomy_active_release",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "revision_id",
            name="uq_canonical_job_taxonomy_active_revision",
        ),
    )

    singleton_key = Column(
        String(64),
        primary_key=True,
        default="canonical-job-taxonomy",
    )
    revision_id = Column(UUID(as_uuid=True), nullable=False)
    content_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CanonicalJobDomain(Base):
    __tablename__ = "canonical_job_domains"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_domain_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_domain_code",
        ),
        UniqueConstraint(
            "revision_id",
            "label",
            name="uq_canonical_job_domain_label",
        ),
        UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_canonical_job_domain_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_domain_code",
        ),
        CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_domain_label",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_domain_order",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_job_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)


class CanonicalJobCategory(Base):
    __tablename__ = "canonical_job_categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["domain_id", "revision_id"],
            ["canonical_job_domains.id", "canonical_job_domains.revision_id"],
            name="fk_canonical_job_category_domain_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_category_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_category_code",
        ),
        UniqueConstraint(
            "domain_id",
            "label",
            name="uq_canonical_job_category_label",
        ),
        UniqueConstraint(
            "domain_id",
            "source_order",
            name="uq_canonical_job_category_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_category_code",
        ),
        CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_category_label",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_category_order",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    domain_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)


class CanonicalJobSubcategory(Base):
    __tablename__ = "canonical_job_subcategories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "revision_id"],
            [
                "canonical_job_categories.id",
                "canonical_job_categories.revision_id",
            ],
            name="fk_canonical_job_subcategory_category_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_subcategory_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_subcategory_code",
        ),
        UniqueConstraint(
            "category_id",
            "label",
            name="uq_canonical_job_subcategory_label",
        ),
        UniqueConstraint(
            "category_id",
            "source_order",
            name="uq_canonical_job_subcategory_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_subcategory_code",
        ),
        CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_subcategory_label",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_subcategory_order",
        ),
        Index(
            "ix_canonical_job_subcategories_assignable",
            "revision_id",
            "is_assignable",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)
    is_assignable = Column(Boolean, nullable=False, default=True)


class CanonicalJobTaxonomyMappingRevision(Base):
    __tablename__ = "canonical_job_taxonomy_mapping_revisions"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "taxonomy_revision_id",
            name="uq_canonical_job_mapping_revision_taxonomy",
        ),
        UniqueConstraint(
            "revision_id",
            "taxonomy_revision_id",
            "content_hash",
            name="uq_canonical_job_mapping_revision_identity",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_mapping_revision_hash",
        ),
        CheckConstraint(
            "expected_coverage_count >= 0 AND expected_entry_count >= 0 "
            "AND expected_target_count >= 0",
            name="ck_canonical_job_mapping_revision_expected_counts",
        ),
        CheckConstraint(
            "materialized_coverage_count >= 0 AND materialized_entry_count >= 0 "
            "AND materialized_target_count >= 0",
            name="ck_canonical_job_mapping_revision_materialized_counts",
        ),
        CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_canonical_job_mapping_revision_status",
        ),
        CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_coverage_count = materialized_coverage_count "
            "AND expected_entry_count = materialized_entry_count "
            "AND expected_target_count = materialized_target_count)",
            name="ck_canonical_job_mapping_revision_ready",
        ),
    )

    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    taxonomy_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_job_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_hash = Column(String(64), nullable=False)
    expected_coverage_count = Column(Integer, nullable=False)
    expected_entry_count = Column(Integer, nullable=False)
    expected_target_count = Column(Integer, nullable=False)
    materialized_coverage_count = Column(Integer, nullable=False, default=0)
    materialized_entry_count = Column(Integer, nullable=False, default=0)
    materialized_target_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="materializing")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    ready_at = Column(DateTime(timezone=True), nullable=True)


class CanonicalJobTaxonomyMappingCoverage(Base):
    __tablename__ = "canonical_job_taxonomy_mapping_coverages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_catalog_revision_id", "source_site"],
            ["source_catalog_revisions.id", "source_catalog_revisions.source_site"],
            name="fk_canonical_job_mapping_coverage_catalog_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "mapping_revision_id",
            "source_site",
            name="uq_canonical_job_mapping_coverage_identity",
        ),
        UniqueConstraint(
            "mapping_revision_id",
            "source_site",
            name="uq_canonical_job_mapping_coverage_source",
        ),
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_canonical_job_mapping_coverage_source",
        ),
        CheckConstraint(
            "source_catalog_sequence > 0 AND identity_count >= 0",
            name="ck_canonical_job_mapping_coverage_counts",
        ),
        CheckConstraint(
            "source_catalog_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND identity_set_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_mapping_coverage_hashes",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mapping_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "canonical_job_taxonomy_mapping_revisions.revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_site = Column(String(32), nullable=False)
    source_catalog_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_catalog_sequence = Column(Integer, nullable=False)
    source_catalog_fingerprint = Column(String(64), nullable=False)
    identity_set_hash = Column(String(64), nullable=False)
    identity_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceJobTaxonomyMapping(Base):
    __tablename__ = "source_job_taxonomy_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["coverage_id", "mapping_revision_id", "source_site"],
            [
                "canonical_job_taxonomy_mapping_coverages.id",
                "canonical_job_taxonomy_mapping_coverages.mapping_revision_id",
                "canonical_job_taxonomy_mapping_coverages.source_site",
            ],
            name="fk_source_job_taxonomy_mapping_coverage",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "mapping_revision_id",
            name="uq_source_job_taxonomy_mapping_id_revision",
        ),
        UniqueConstraint(
            "mapping_revision_id",
            "source_site",
            "source_classification_id",
            name="uq_source_job_taxonomy_mapping_identity",
        ),
        UniqueConstraint(
            "mapping_revision_id",
            "source_order",
            name="uq_source_job_taxonomy_mapping_order",
        ),
        CheckConstraint(
            "disposition IN ('deterministic', 'allowed_slice', 'excluded', 'unmapped')",
            name="ck_source_job_taxonomy_mapping_disposition",
        ),
        CheckConstraint(
            "source_classification_id LIKE source_site || ':%' "
            "AND length(source_classification_id) > length(source_site) + 1",
            name="ck_source_job_taxonomy_mapping_identity",
        ),
        CheckConstraint(
            "source_order > 0 AND length(trim(source_label)) > 0",
            name="ck_source_job_taxonomy_mapping_content",
        ),
        Index(
            "ix_source_job_taxonomy_mapping_lookup",
            "mapping_revision_id",
            "source_site",
            "source_classification_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mapping_revision_id = Column(UUID(as_uuid=True), nullable=False)
    coverage_id = Column(UUID(as_uuid=True), nullable=False)
    source_site = Column(String(32), nullable=False)
    source_classification_id = Column(String(255), nullable=False)
    source_label = Column(String(255), nullable=False)
    disposition = Column(String(32), nullable=False)
    source_order = Column(Integer, nullable=False)
    review_evidence = Column(JSON, nullable=False, default=dict)


class SourceJobTaxonomyMappingTarget(Base):
    __tablename__ = "source_job_taxonomy_mapping_targets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mapping_id", "mapping_revision_id"],
            [
                "source_job_taxonomy_mappings.id",
                "source_job_taxonomy_mappings.mapping_revision_id",
            ],
            name="fk_source_job_taxonomy_mapping_target_mapping",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subcategory_id", "taxonomy_revision_id"],
            [
                "canonical_job_subcategories.id",
                "canonical_job_subcategories.revision_id",
            ],
            name="fk_source_job_taxonomy_mapping_target_subcategory",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "mapping_id",
            "subcategory_id",
            name="uq_source_job_taxonomy_mapping_target",
        ),
        UniqueConstraint(
            "mapping_id",
            "source_order",
            name="uq_source_job_taxonomy_mapping_target_order",
        ),
        CheckConstraint(
            "role IN ('deterministic', 'allowed')",
            name="ck_source_job_taxonomy_mapping_target_role",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_source_job_taxonomy_mapping_target_order",
        ),
        Index(
            "ix_source_job_taxonomy_mapping_targets_subcategory",
            "taxonomy_revision_id",
            "subcategory_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mapping_id = Column(UUID(as_uuid=True), nullable=False)
    mapping_revision_id = Column(UUID(as_uuid=True), nullable=False)
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    subcategory_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(String(32), nullable=False)
    source_order = Column(Integer, nullable=False)


class CanonicalJobTaxonomyActiveMappingRevision(Base):
    __tablename__ = "canonical_job_taxonomy_active_mapping_revisions"
    __table_args__ = (
        CheckConstraint(
            "singleton_key = 'canonical-job-taxonomy-mapping'",
            name="ck_canonical_job_mapping_active_singleton",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_canonical_job_mapping_active_version",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "taxonomy_revision_id", "content_hash"],
            [
                "canonical_job_taxonomy_mapping_revisions.revision_id",
                "canonical_job_taxonomy_mapping_revisions.taxonomy_revision_id",
                "canonical_job_taxonomy_mapping_revisions.content_hash",
            ],
            name="fk_canonical_job_mapping_active_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "mapping_revision_id",
            name="uq_canonical_job_mapping_active_revision",
        ),
    )

    singleton_key = Column(
        String(64),
        primary_key=True,
        default="canonical-job-taxonomy-mapping",
    )
    mapping_revision_id = Column(UUID(as_uuid=True), nullable=False)
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    content_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class JobTaxonomyAssignment(Base):
    __tablename__ = "job_taxonomy_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["subcategory_id", "taxonomy_revision_id"],
            [
                "canonical_job_subcategories.id",
                "canonical_job_subcategories.revision_id",
            ],
            name="fk_job_taxonomy_assignment_subcategory",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "taxonomy_revision_id"],
            [
                "canonical_job_taxonomy_mapping_revisions.revision_id",
                "canonical_job_taxonomy_mapping_revisions.taxonomy_revision_id",
            ],
            name="fk_job_taxonomy_assignment_mapping_taxonomy",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "method IN ('reviewed_mapping', 'constrained_ai', 'operator')",
            name="ck_job_taxonomy_assignment_method",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_job_taxonomy_assignment_evidence_hash",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_job_taxonomy_assignment_version",
        ),
        CheckConstraint(
            "(is_current AND superseded_at IS NULL) OR "
            "(NOT is_current AND superseded_at IS NOT NULL)",
            name="ck_job_taxonomy_assignment_current",
        ),
        Index(
            "ux_job_taxonomy_assignment_current",
            "job_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        Index(
            "ix_job_taxonomy_assignments_subcategory",
            "taxonomy_revision_id",
            "subcategory_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    subcategory_id = Column(UUID(as_uuid=True), nullable=False)
    mapping_revision_id = Column(UUID(as_uuid=True), nullable=True)
    method = Column(String(32), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    source_evidence_refs = Column(JSON, nullable=False, default=list)
    mapping_ids = Column(JSON, nullable=False, default=list)
    model_provider = Column(String(100), nullable=True)
    model_name = Column(String(255), nullable=True)
    model_version = Column(String(255), nullable=True)
    breadcrumb = Column(JSON, nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at = Column(DateTime(timezone=True), nullable=True)


class JobTaxonomyReviewItem(Base):
    __tablename__ = "job_taxonomy_review_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mapping_revision_id", "taxonomy_revision_id"],
            [
                "canonical_job_taxonomy_mapping_revisions.revision_id",
                "canonical_job_taxonomy_mapping_revisions.taxonomy_revision_id",
            ],
            name="fk_job_taxonomy_review_mapping_taxonomy",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active', 'assigned', 'insufficient_evidence', 'superseded')",
            name="ck_job_taxonomy_review_status",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' AND lock_version > 0",
            name="ck_job_taxonomy_review_evidence_version",
        ),
        CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_job_taxonomy_review_resolution",
        ),
        Index(
            "ux_job_taxonomy_review_active",
            "job_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_job_taxonomy_review_items_status_created",
            "status",
            "created_at",
            "id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("canonical_job_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    mapping_revision_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    reasons = Column(JSON, nullable=False, default=list)
    evidence_hash = Column(String(64), nullable=False)
    evidence_refs = Column(JSON, nullable=False, default=list)
    recommendations = Column(JSON, nullable=False, default=list)
    lock_version = Column(Integer, nullable=False, default=1)
    decision_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_taxonomy_assignments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)


def _prevent_immutable_content_update(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


def _prevent_immutable_content_delete(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


for _immutable_model in (
    CanonicalJobDomain,
    CanonicalJobCategory,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyMappingCoverage,
    SourceJobTaxonomyMapping,
    SourceJobTaxonomyMappingTarget,
):
    event.listen(
        _immutable_model,
        "before_update",
        _prevent_immutable_content_update,
    )
    event.listen(
        _immutable_model,
        "before_delete",
        _prevent_immutable_content_delete,
    )


CANONICAL_JOB_TAXONOMY_TABLES = (
    CanonicalJobTaxonomyRelease.__table__,
    CanonicalJobTaxonomyActiveRevision.__table__,
    CanonicalJobDomain.__table__,
    CanonicalJobCategory.__table__,
    CanonicalJobSubcategory.__table__,
    CanonicalJobTaxonomyMappingRevision.__table__,
    CanonicalJobTaxonomyMappingCoverage.__table__,
    SourceJobTaxonomyMapping.__table__,
    SourceJobTaxonomyMappingTarget.__table__,
    CanonicalJobTaxonomyActiveMappingRevision.__table__,
    JobTaxonomyAssignment.__table__,
    JobTaxonomyReviewItem.__table__,
)
