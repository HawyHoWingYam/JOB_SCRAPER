from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    text,
    UniqueConstraint,
    Uuid,
)

from app.database import Base
from app.utils.time import utc_now


class CurrentTaxonomyNodeRecord(Base):
    __tablename__ = "current_taxonomy_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "parent_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_taxonomy_node_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "taxonomy IN ('job', 'company_industry', 'skill')",
            name="ck_current_taxonomy_node_taxonomy",
        ),
        CheckConstraint("length(code) > 0", name="ck_current_taxonomy_node_code"),
        CheckConstraint("sort_order >= 0", name="ck_current_taxonomy_node_order"),
        Index(
            "ix_current_taxonomy_node_parent",
            "taxonomy",
            "parent_code",
            "sort_order",
        ),
    )

    taxonomy = Column(String(32), primary_key=True)
    code = Column(String(255), primary_key=True)
    parent_code = Column(String(255), nullable=True)
    level = Column(String(32), nullable=False)
    labels = Column(JSON, nullable=False)
    sort_order = Column(Integer, nullable=False)
    is_assignable = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)


class CurrentTaxonomyAliasRecord(Base):
    __tablename__ = "current_taxonomy_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "node_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_taxonomy_alias_node",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "taxonomy IN ('job', 'company_industry', 'skill')",
            name="ck_current_taxonomy_alias_taxonomy",
        ),
        Index(
            "ix_current_taxonomy_alias_lookup",
            "taxonomy",
            "normalized_alias",
        ),
    )

    taxonomy = Column(String(32), primary_key=True)
    node_code = Column(String(255), primary_key=True)
    alias = Column(String(255), primary_key=True)
    normalized_alias = Column(String(255), nullable=False)


class CurrentJobTaxonomyAssignment(Base):
    __tablename__ = "current_job_taxonomy_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "taxonomy_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_job_taxonomy_assignment_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint("taxonomy = 'job'", name="ck_current_job_assignment_taxonomy"),
    )

    job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    taxonomy = Column(String(32), nullable=False, default="job")
    taxonomy_code = Column(String(255), nullable=False, index=True)
    method = Column(String(32), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    source_evidence_refs = Column(JSON, nullable=False, default=list)
    mapping_ids = Column(JSON, nullable=False, default=list)
    model_provenance = Column(JSON, nullable=True)
    breadcrumb = Column(JSON, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CurrentCompanyIndustryAssignment(Base):
    __tablename__ = "current_company_industry_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "taxonomy_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_company_industry_assignment_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "taxonomy = 'company_industry'",
            name="ck_current_company_assignment_taxonomy",
        ),
        UniqueConstraint(
            "company_id",
            "taxonomy_code",
            name="uq_current_company_industry_assignment",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy = Column(String(32), nullable=False, default="company_industry")
    taxonomy_code = Column(String(255), nullable=False, index=True)
    method = Column(String(32), nullable=False)
    provenance = Column(JSON, nullable=False, default=dict)
    evidence_hash = Column(String(64), nullable=False)
    breadcrumb = Column(JSON, nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    primary_basis = Column(String(32), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CurrentJobSkillAssignment(Base):
    __tablename__ = "current_job_skill_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "skill_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_job_skill_assignment_node",
            ondelete="RESTRICT",
        ),
        CheckConstraint("taxonomy = 'skill'", name="ck_current_job_skill_taxonomy"),
    )

    job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_code = Column(String(255), primary_key=True)
    taxonomy = Column(String(32), nullable=False, default="skill")
    source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    mention_count = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CurrentSkillCandidate(Base):
    __tablename__ = "current_skill_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "resolved_skill_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_skill_candidate_resolved_skill",
            ondelete="RESTRICT",
        ),
        CheckConstraint("taxonomy = 'skill'", name="ck_current_skill_candidate_taxonomy"),
        CheckConstraint(
            "occurrence_count >= 0 AND distinct_job_count >= 0",
            name="ck_current_skill_candidate_metrics",
        ),
        UniqueConstraint(
            "normalized_key",
            name="uq_current_skill_candidate_normalized_key",
        ),
        Index(
            "ix_current_skill_candidate_threshold",
            "occurrence_count",
            "last_seen_at",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    taxonomy = Column(String(32), nullable=False, default="skill")
    normalized_key = Column(String(500), nullable=False)
    canonical_raw_name = Column(String(500), nullable=False)
    raw_variants = Column(JSON, nullable=False, default=list)
    occurrence_count = Column(Integer, nullable=False, default=0)
    distinct_job_count = Column(Integer, nullable=False, default=0)
    evidence_summary = Column(JSON, nullable=False, default=dict)
    resolved_skill_code = Column(String(255), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CurrentJobSkillMention(Base):
    __tablename__ = "current_job_skill_mentions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "skill_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_job_skill_mention_skill",
            ondelete="RESTRICT",
        ),
        CheckConstraint("taxonomy = 'skill'", name="ck_current_job_skill_mention_taxonomy"),
        CheckConstraint(
            "resolution IN ('match_existing', 'candidate', "
            "'generic_tag', 'rejected')",
            name="ck_current_job_skill_mention_resolution",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_current_job_skill_mention_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_current_job_skill_mention_confidence",
        ),
        CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL)",
            name="ck_current_job_skill_mention_superseded",
        ),
        CheckConstraint(
            "(resolution = 'match_existing' AND skill_code IS NOT NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'candidate' AND skill_code IS NULL "
            "AND candidate_id IS NOT NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'generic_tag' AND skill_code IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NOT NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'rejected' AND skill_code IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NOT NULL)",
            name="ck_current_job_skill_mention_target",
        ),
        Index(
            "ux_current_job_skill_mention_active_key",
            "job_id",
            "normalized_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_current_job_skill_mention_candidate",
            "candidate_id",
            "resolution",
            "job_id",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taxonomy = Column(String(32), nullable=False, default="skill")
    raw_name = Column(String(500), nullable=False)
    normalized_key = Column(String(500), nullable=False)
    resolution = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    skill_code = Column(String(255), nullable=True)
    candidate_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("current_skill_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    origin_candidate_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("current_skill_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    generic_tag = Column(String(500), nullable=True)
    rejection_reason = Column(String, nullable=True)
    source = Column(String(64), nullable=False, default="ai-extraction")
    confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    evidence_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at = Column(DateTime(timezone=True), nullable=True)


class CurrentSourceTaxonomyMapping(Base):
    __tablename__ = "current_source_taxonomy_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy", "target_code"],
            ["current_taxonomy_nodes.taxonomy", "current_taxonomy_nodes.code"],
            name="fk_current_source_taxonomy_mapping_target",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "role IN ('deterministic', 'allowed')",
            name="ck_current_source_taxonomy_mapping_role",
        ),
        Index(
            "ix_current_source_taxonomy_mapping_lookup",
            "taxonomy",
            "source_site",
            "source_key",
        ),
    )

    taxonomy = Column(String(32), primary_key=True)
    source_site = Column(String(32), primary_key=True)
    source_key = Column(String(500), primary_key=True)
    target_code = Column(String(255), primary_key=True)
    source_label = Column(String(500), nullable=True)
    role = Column(String(32), nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)


CURRENT_TAXONOMY_TABLES = (
    CurrentTaxonomyNodeRecord.__table__,
    CurrentTaxonomyAliasRecord.__table__,
    CurrentJobTaxonomyAssignment.__table__,
    CurrentCompanyIndustryAssignment.__table__,
    CurrentJobSkillAssignment.__table__,
    CurrentSkillCandidate.__table__,
    CurrentJobSkillMention.__table__,
    CurrentSourceTaxonomyMapping.__table__,
)
