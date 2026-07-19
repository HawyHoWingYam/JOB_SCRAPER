from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
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
from sqlalchemy import UUID

from app.database import Base
from app.utils.time import utc_now


class CompanyIndustryTaxonomyRelease(Base):
    __tablename__ = "company_industry_taxonomy_releases"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "content_hash",
            name="uq_company_industry_release_hash",
        ),
        CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_company_industry_release_status",
        ),
        CheckConstraint(
            "expected_total >= 0 AND materialized_total >= 0",
            name="ck_company_industry_release_counts",
        ),
        CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_total = materialized_total)",
            name="ck_company_industry_release_ready",
        ),
    )

    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    standard = Column(String(32), nullable=False)
    release = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_metadata = Column(JSON, nullable=False)
    expected_counts = Column(JSON, nullable=False)
    materialized_counts = Column(JSON, nullable=False, default=dict)
    expected_total = Column(Integer, nullable=False)
    materialized_total = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="materializing")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    ready_at = Column(DateTime(timezone=True), nullable=True)


class CompanyIndustryActiveRevision(Base):
    __tablename__ = "company_industry_active_revisions"
    __table_args__ = (
        CheckConstraint(
            "singleton_key = 'company-industry'",
            name="ck_company_industry_active_singleton",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_active_version",
        ),
        ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "company_industry_taxonomy_releases.revision_id",
                "company_industry_taxonomy_releases.content_hash",
            ],
            name="fk_company_industry_active_release",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "revision_id",
            name="uq_company_industry_active_revision",
        ),
    )

    singleton_key = Column(String(64), primary_key=True, default="company-industry")
    revision_id = Column(UUID(as_uuid=True), nullable=False)
    content_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CompanyIndustryTaxonomyNode(Base):
    __tablename__ = "company_industry_taxonomy_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["parent_id", "revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_node_parent_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_company_industry_node_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_company_industry_node_code",
        ),
        UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_company_industry_node_order",
        ),
        CheckConstraint(
            "level IN ('section', 'division', 'group', 'class', 'subclass')",
            name="ck_company_industry_node_level",
        ),
        CheckConstraint(
            "(level = 'section' AND parent_id IS NULL) OR "
            "(level <> 'section' AND parent_id IS NOT NULL)",
            name="ck_company_industry_node_parent",
        ),
        CheckConstraint(
            "length(trim(code)) > 0 AND length(trim(label_en)) > 0 "
            "AND length(trim(label_zh_hant)) > 0 "
            "AND length(trim(label_zh_hans)) > 0",
            name="ck_company_industry_node_labels",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_company_industry_node_order",
        ),
        Index(
            "ix_company_industry_nodes_parent",
            "revision_id",
            "parent_id",
            "source_order",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "company_industry_taxonomy_releases.revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    code = Column(String(6), nullable=False)
    parent_id = Column(UUID(as_uuid=True), nullable=True)
    level = Column(String(32), nullable=False)
    label_en = Column(String(500), nullable=False)
    label_zh_hant = Column(String(500), nullable=False)
    label_zh_hans = Column(String(500), nullable=False)
    source_order = Column(Integer, nullable=False)
    is_assignable = Column(Boolean, nullable=False, default=True)
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)
    source_metadata = Column(JSON, nullable=False, default=dict)


class CompanyIndustryCrosswalkEdge(Base):
    __tablename__ = "company_industry_crosswalk_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["hsic_node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_crosswalk_hsic_node",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "taxonomy_revision_id",
            "hsic_node_id",
            "target_standard",
            "target_release",
            "target_code",
            name="uq_company_industry_crosswalk_edge",
        ),
        CheckConstraint(
            "cardinality IN ('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many')",
            name="ck_company_industry_crosswalk_cardinality",
        ),
        CheckConstraint(
            "method IN ('official', 'project_validated')",
            name="ck_company_industry_crosswalk_method",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_company_industry_crosswalk_confidence",
        ),
        CheckConstraint(
            "source_order > 0",
            name="ck_company_industry_crosswalk_order",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    hsic_node_id = Column(UUID(as_uuid=True), nullable=False)
    target_standard = Column(String(32), nullable=False)
    target_release = Column(String(64), nullable=False)
    target_code = Column(String(64), nullable=False)
    cardinality = Column(String(32), nullable=False)
    method = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False)
    source_order = Column(Integer, nullable=False)


class SourceIndustryMapping(Base):
    __tablename__ = "source_industry_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["target_node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_source_industry_mapping_target",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "key_kind IN ('code', 'label')",
            name="ck_source_industry_mapping_key_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'retired')",
            name="ck_source_industry_mapping_status",
        ),
        CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status IN ('superseded', 'retired') AND superseded_at IS NOT NULL)",
            name="ck_source_industry_mapping_superseded",
        ),
        CheckConstraint(
            "approved_by = 'local-operator' AND lock_version > 0",
            name="ck_source_industry_mapping_approval",
        ),
        Index(
            "ux_source_industry_mapping_active",
            "source_site",
            "key_kind",
            "normalized_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False)
    key_kind = Column(String(16), nullable=False)
    raw_value = Column(String(500), nullable=False)
    normalized_key = Column(String(500), nullable=False)
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    target_node_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    lock_version = Column(Integer, nullable=False, default=1)
    approved_by = Column(String(64), nullable=False)
    approved_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    decision_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at = Column(DateTime(timezone=True), nullable=True)


class CompanyIndustryAssignment(Base):
    __tablename__ = "company_industry_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_assignment_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "method IN ('authoritative_code', 'reviewed_mapping', 'operator')",
            name="ck_company_industry_assignment_method",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_company_industry_assignment_status",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_company_industry_assignment_hash",
        ),
        CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL)",
            name="ck_company_industry_assignment_superseded",
        ),
        CheckConstraint(
            "(is_primary AND primary_basis IN ('authoritative_source', 'operator')) OR "
            "(NOT is_primary AND primary_basis IS NULL)",
            name="ck_company_industry_assignment_primary_basis",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_assignment_version",
        ),
        Index(
            "ux_company_industry_assignment_active_node",
            "company_id",
            "node_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ux_company_industry_assignment_primary",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'active' AND is_primary"),
            sqlite_where=text("status = 'active' AND is_primary = 1"),
        ),
        Index(
            "ix_company_industry_assignments_node",
            "taxonomy_revision_id",
            "node_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False)
    node_id = Column(UUID(as_uuid=True), nullable=False)
    mapping_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_industry_mappings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    method = Column(String(32), nullable=False)
    provenance = Column(JSON, nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    breadcrumb = Column(JSON, nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    primary_basis = Column(String(32), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    lock_version = Column(Integer, nullable=False, default=1)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at = Column(DateTime(timezone=True), nullable=True)


class CompanyIndustryReviewItem(Base):
    __tablename__ = "company_industry_review_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'assigned', 'insufficient_evidence', "
            "'not_company_industry', 'superseded')",
            name="ck_company_industry_review_status",
        ),
        CheckConstraint(
            "reason IN ('taxonomy_not_active', 'unmapped_source_evidence', "
            "'manual_evidence', 'ai_recommendation', 'invalid_hsic_code', "
            "'conflicting_hsic_codes', 'conflicting_source_mapping', "
            "'not_company_industry')",
            name="ck_company_industry_review_reason",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_review_version",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_company_industry_review_hash",
        ),
        CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_company_industry_review_resolution",
        ),
        Index(
            "ux_company_industry_review_active_evidence",
            "company_id",
            "evidence_hash",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_company_industry_review_status_created",
            "status",
            "created_at",
            "id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "company_industry_taxonomy_releases.revision_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    source_site = Column(String(32), nullable=True)
    key_kind = Column(String(16), nullable=True)
    raw_value = Column(String(500), nullable=True)
    normalized_key = Column(String(500), nullable=True)
    reason = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    evidence_hash = Column(String(64), nullable=False)
    provenance = Column(JSON, nullable=False)
    recommendations = Column(JSON, nullable=False, default=list)
    lock_version = Column(Integer, nullable=False, default=1)
    decision_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("company_industry_assignments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    mapping_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_industry_mappings.id", ondelete="RESTRICT"),
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


def _prevent_immutable_update(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


def _prevent_immutable_delete(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


for _immutable_model in (
    CompanyIndustryTaxonomyNode,
    CompanyIndustryCrosswalkEdge,
):
    event.listen(_immutable_model, "before_update", _prevent_immutable_update)
    event.listen(_immutable_model, "before_delete", _prevent_immutable_delete)


COMPANY_INDUSTRY_TABLES = (
    CompanyIndustryTaxonomyRelease.__table__,
    CompanyIndustryActiveRevision.__table__,
    CompanyIndustryTaxonomyNode.__table__,
    CompanyIndustryCrosswalkEdge.__table__,
    SourceIndustryMapping.__table__,
    CompanyIndustryAssignment.__table__,
    CompanyIndustryReviewItem.__table__,
)


__all__ = [
    "COMPANY_INDUSTRY_TABLES",
    "CompanyIndustryActiveRevision",
    "CompanyIndustryAssignment",
    "CompanyIndustryCrosswalkEdge",
    "CompanyIndustryReviewItem",
    "CompanyIndustryTaxonomyNode",
    "CompanyIndustryTaxonomyRelease",
    "SourceIndustryMapping",
]
