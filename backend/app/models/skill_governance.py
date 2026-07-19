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
    Text,
    UniqueConstraint,
    event,
    inspect as sa_inspect,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class SkillTaxonomyRelease(Base):
    __tablename__ = "skill_taxonomy_releases"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "content_hash",
            name="uq_skill_taxonomy_release_hash",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$' AND "
            "taxonomy_hash ~ '^[0-9a-f]{64}$' AND "
            "rules_hash ~ '^[0-9a-f]{64}$' AND "
            "backfill_hash ~ '^[0-9a-f]{64}$'",
            name="ck_skill_taxonomy_release_hashes",
        ),
        CheckConstraint(
            "expected_category_count >= 0 AND expected_technology_count >= 0 "
            "AND expected_skill_count >= 0 AND expected_alias_count >= 0",
            name="ck_skill_taxonomy_release_expected_counts",
        ),
        CheckConstraint(
            "materialized_category_count >= 0 AND materialized_technology_count >= 0 "
            "AND materialized_skill_count >= 0 AND materialized_alias_count >= 0",
            name="ck_skill_taxonomy_release_materialized_counts",
        ),
        CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_skill_taxonomy_release_status",
        ),
        CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_category_count = materialized_category_count "
            "AND expected_technology_count = materialized_technology_count "
            "AND expected_skill_count = materialized_skill_count "
            "AND expected_alias_count = materialized_alias_count)",
            name="ck_skill_taxonomy_release_ready",
        ),
    )

    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    content_hash = Column(String(64), nullable=False)
    taxonomy_hash = Column(String(64), nullable=False)
    rules_hash = Column(String(64), nullable=False)
    backfill_hash = Column(String(64), nullable=False)
    rules_document = Column(JSON, nullable=False)
    backfill_document = Column(JSON, nullable=False)
    expected_category_count = Column(Integer, nullable=False)
    expected_technology_count = Column(Integer, nullable=False)
    expected_skill_count = Column(Integer, nullable=False)
    expected_alias_count = Column(Integer, nullable=False)
    materialized_category_count = Column(Integer, nullable=False, default=0)
    materialized_technology_count = Column(Integer, nullable=False, default=0)
    materialized_skill_count = Column(Integer, nullable=False, default=0)
    materialized_alias_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="materializing")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    ready_at = Column(DateTime(timezone=True), nullable=True)


class SkillTaxonomyActiveRevision(Base):
    __tablename__ = "skill_taxonomy_active_revisions"
    __table_args__ = (
        CheckConstraint(
            "singleton_key = 'skill-taxonomy'",
            name="ck_skill_taxonomy_active_singleton",
        ),
        CheckConstraint(
            "lock_version > 0",
            name="ck_skill_taxonomy_active_version",
        ),
        ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "skill_taxonomy_releases.revision_id",
                "skill_taxonomy_releases.content_hash",
            ],
            name="fk_skill_taxonomy_active_release",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "revision_id",
            name="uq_skill_taxonomy_active_revision",
        ),
    )

    singleton_key = Column(String(64), primary_key=True, default="skill-taxonomy")
    revision_id = Column(UUID(as_uuid=True), nullable=False)
    content_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class GovernedSkillCategory(Base):
    __tablename__ = "governed_skill_categories"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_category_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_category_code",
        ),
        UniqueConstraint(
            "revision_id",
            "name",
            name="uq_governed_skill_category_name",
        ),
        UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_governed_skill_category_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_category_code",
        ),
        CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_category_content",
        ),
        CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_category_retirement",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("skill_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)


class GovernedSkillTechnology(Base):
    __tablename__ = "governed_skill_technologies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "revision_id"],
            [
                "governed_skill_categories.id",
                "governed_skill_categories.revision_id",
            ],
            name="fk_governed_skill_technology_category",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_technology_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_technology_code",
        ),
        UniqueConstraint(
            "category_id",
            "name",
            name="uq_governed_skill_technology_name",
        ),
        UniqueConstraint(
            "category_id",
            "source_order",
            name="uq_governed_skill_technology_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_technology_code",
        ),
        CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_technology_content",
        ),
        CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_technology_retirement",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)


class GovernedSkill(Base):
    __tablename__ = "governed_skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["technology_id", "revision_id"],
            [
                "governed_skill_technologies.id",
                "governed_skill_technologies.revision_id",
            ],
            name="fk_governed_skill_technology",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_id_revision",
        ),
        UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_code",
        ),
        UniqueConstraint(
            "technology_id",
            "name",
            name="uq_governed_skill_name",
        ),
        UniqueConstraint(
            "technology_id",
            "source_order",
            name="uq_governed_skill_order",
        ),
        CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_code",
        ),
        CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_content",
        ),
        CheckConstraint(
            "origin IN ('seed', 'operator')",
            name="ck_governed_skill_origin",
        ),
        CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_retirement",
        ),
        Index(
            "ix_governed_skills_active",
            "revision_id",
            "is_active",
            "code",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    technology_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    source_order = Column(Integer, nullable=False)
    origin = Column(String(32), nullable=False, default="seed")
    is_active = Column(Boolean, nullable=False, default=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
    created_by_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )


class GovernedSkillAlias(Base):
    __tablename__ = "governed_skill_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_skill_alias_skill",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "taxonomy_revision_id",
            "normalized_key",
            name="uq_governed_skill_alias_key",
        ),
        UniqueConstraint(
            "skill_id",
            "source_order",
            name="uq_governed_skill_alias_order",
        ),
        CheckConstraint(
            "source IN ('canonical_name', 'taxonomy_alias', 'curation_alias', 'operator')",
            name="ck_governed_skill_alias_source",
        ),
        CheckConstraint(
            "length(trim(raw_alias)) > 0 AND length(trim(normalized_key)) > 0 "
            "AND source_order > 0",
            name="ck_governed_skill_alias_content",
        ),
        Index(
            "ix_governed_skill_alias_lookup",
            "taxonomy_revision_id",
            "normalized_key",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    taxonomy_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    skill_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    raw_alias = Column(String(500), nullable=False)
    normalized_key = Column(String(500), nullable=False)
    source = Column(String(32), nullable=False)
    source_order = Column(Integer, nullable=False)
    created_by_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )


class SkillCandidate(Base):
    __tablename__ = "skill_candidates"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "taxonomy_revision_id",
            name="uq_skill_candidate_id_revision",
        ),
        UniqueConstraint(
            "taxonomy_revision_id",
            "normalized_key",
            name="uq_skill_candidate_key_revision",
        ),
        ForeignKeyConstraint(
            ["resolved_skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_skill_candidate_resolved_skill",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved_merged', 'resolved_created', "
            "'resolved_generic', 'rejected', 'superseded')",
            name="ck_skill_candidate_status",
        ),
        CheckConstraint(
            "occurrence_count >= 0 AND distinct_job_count >= 0 AND lock_version > 0",
            name="ck_skill_candidate_metrics_version",
        ),
        CheckConstraint(
            "length(trim(normalized_key)) > 0 AND length(trim(canonical_raw_name)) > 0",
            name="ck_skill_candidate_identity",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status IN ('resolved_merged', 'resolved_created') "
            "AND resolved_at IS NOT NULL AND resolved_skill_id IS NOT NULL "
            "AND generic_tag IS NULL AND rejection_reason IS NULL) OR "
            "(status = 'resolved_generic' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NOT NULL "
            "AND length(trim(generic_tag)) > 0 "
            "AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0) OR "
            "(status = 'superseded' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL)",
            name="ck_skill_candidate_resolution",
        ),
        Index(
            "ix_skill_candidates_queue",
            "status",
            "last_seen_at",
            "id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    taxonomy_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("skill_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    normalized_key = Column(String(500), nullable=False)
    canonical_raw_name = Column(String(500), nullable=False)
    raw_variants = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="pending")
    suggested_category_code = Column(String(255), nullable=True)
    suggested_technology_code = Column(String(255), nullable=True)
    occurrence_count = Column(Integer, nullable=False, default=0)
    distinct_job_count = Column(Integer, nullable=False, default=0)
    evidence_summary = Column(JSON, nullable=False, default=dict)
    recommendations = Column(JSON, nullable=False, default=list)
    lock_version = Column(Integer, nullable=False, default=1)
    decision_audit_id = Column(
        UUID(as_uuid=True),
        ForeignKey("governance_audit_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    resolved_skill_id = Column(UUID(as_uuid=True), nullable=True)
    generic_tag = Column(String(500), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class GovernedJobSkillMention(Base):
    __tablename__ = "governed_job_skill_mentions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_job_skill_mention_skill",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "taxonomy_revision_id"],
            ["skill_candidates.id", "skill_candidates.taxonomy_revision_id"],
            name="fk_governed_job_skill_mention_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["origin_candidate_id", "taxonomy_revision_id"],
            ["skill_candidates.id", "skill_candidates.taxonomy_revision_id"],
            name="fk_governed_job_skill_mention_origin_candidate",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "resolution IN ('match_existing', 'review_candidate', 'generic_tag', 'rejected')",
            name="ck_governed_job_skill_mention_resolution",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_governed_job_skill_mention_status",
        ),
        CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL)",
            name="ck_governed_job_skill_mention_superseded",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_governed_job_skill_mention_confidence",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' AND lock_version > 0 "
            "AND length(trim(raw_name)) > 0 AND length(trim(normalized_key)) > 0",
            name="ck_governed_job_skill_mention_content",
        ),
        CheckConstraint(
            "(resolution = 'match_existing' AND skill_id IS NOT NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'review_candidate' AND skill_id IS NULL "
            "AND candidate_id IS NOT NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'generic_tag' AND skill_id IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NOT NULL "
            "AND length(trim(generic_tag)) > 0 "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'rejected' AND skill_id IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0)",
            name="ck_governed_job_skill_mention_target",
        ),
        Index(
            "ux_governed_job_skill_mention_active_key",
            "job_id",
            "taxonomy_revision_id",
            "normalized_key",
            unique=True,
            postgresql_where=sa_text("status = 'active'"),
            sqlite_where=sa_text("status = 'active'"),
        ),
        Index(
            "ix_governed_job_skill_mentions_candidate",
            "candidate_id",
            "resolution",
            "job_id",
        ),
        Index(
            "ix_governed_job_skill_mentions_skill",
            "taxonomy_revision_id",
            "skill_id",
            "job_id",
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
        ForeignKey("skill_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    raw_name = Column(String(500), nullable=False)
    normalized_key = Column(String(500), nullable=False)
    resolution = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    skill_id = Column(UUID(as_uuid=True), nullable=True)
    candidate_id = Column(UUID(as_uuid=True), nullable=True)
    origin_candidate_id = Column(UUID(as_uuid=True), nullable=True)
    generic_tag = Column(String(500), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    source = Column(String(64), nullable=False, default="ai-extraction")
    confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    evidence_hash = Column(String(64), nullable=False)
    lock_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    superseded_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="governed_skill_mentions")
    skill = relationship(
        "GovernedSkill",
        foreign_keys=[skill_id, taxonomy_revision_id],
        viewonly=True,
    )
    candidate = relationship(
        "SkillCandidate",
        foreign_keys=[candidate_id, taxonomy_revision_id],
        viewonly=True,
    )


class GovernedJobSkill(Base):
    __tablename__ = "governed_job_skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_job_skill_skill",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "job_id",
            "taxonomy_revision_id",
            "skill_id",
            name="uq_governed_job_skill_projection",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_governed_job_skill_confidence",
        ),
        CheckConstraint(
            "mention_count > 0",
            name="ck_governed_job_skill_mention_count",
        ),
        Index(
            "ix_governed_job_skills_filter",
            "taxonomy_revision_id",
            "skill_id",
            "job_id",
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
        ForeignKey("skill_taxonomy_releases.revision_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    skill_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    mention_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    job = relationship("Job", back_populates="governed_job_skills")
    skill = relationship(
        "GovernedSkill",
        foreign_keys=[skill_id, taxonomy_revision_id],
        viewonly=True,
    )


def _prevent_immutable_update(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


def _prevent_immutable_delete(_mapper, _connection, record) -> None:
    raise ValueError(f"{record.__tablename__} rows are immutable")


for _immutable_model in (GovernedSkillCategory, GovernedSkillTechnology):
    event.listen(_immutable_model, "before_update", _prevent_immutable_update)
    event.listen(_immutable_model, "before_delete", _prevent_immutable_delete)


def _allow_audit_attachment_only(record, attribute_name: str) -> bool:
    state = sa_inspect(record)
    changed = {
        attribute.key
        for attribute in state.mapper.column_attrs
        if state.attrs[attribute.key].history.has_changes()
    }
    history = state.attrs[attribute_name].history
    operator_owned = (
        record.origin == "operator"
        if isinstance(record, GovernedSkill)
        else record.source == "operator"
    )
    return (
        changed == {attribute_name}
        and operator_owned
        and bool(history.added)
        and history.added[0] is not None
    )


@event.listens_for(GovernedSkill, "before_update")
def _guard_governed_skill_update(_mapper, _connection, record) -> None:
    if not _allow_audit_attachment_only(record, "created_by_audit_id"):
        _prevent_immutable_update(_mapper, _connection, record)


@event.listens_for(GovernedSkillAlias, "before_update")
def _guard_governed_skill_alias_update(_mapper, _connection, record) -> None:
    if not _allow_audit_attachment_only(record, "created_by_audit_id"):
        _prevent_immutable_update(_mapper, _connection, record)


for _immutable_model in (GovernedSkill, GovernedSkillAlias):
    event.listen(_immutable_model, "before_delete", _prevent_immutable_delete)


@event.listens_for(SkillTaxonomyActiveRevision, "before_delete")
def _prevent_active_revision_delete(_mapper, _connection, _record) -> None:
    raise ValueError("Skill taxonomy active revision cannot be deleted")


SKILL_GOVERNANCE_TABLES = (
    SkillTaxonomyRelease.__table__,
    SkillTaxonomyActiveRevision.__table__,
    GovernedSkillCategory.__table__,
    GovernedSkillTechnology.__table__,
    GovernedSkill.__table__,
    GovernedSkillAlias.__table__,
    SkillCandidate.__table__,
    GovernedJobSkillMention.__table__,
    GovernedJobSkill.__table__,
)


__all__ = [
    "SKILL_GOVERNANCE_TABLES",
    "GovernedJobSkill",
    "GovernedJobSkillMention",
    "GovernedSkill",
    "GovernedSkillAlias",
    "GovernedSkillCategory",
    "GovernedSkillTechnology",
    "SkillCandidate",
    "SkillTaxonomyActiveRevision",
    "SkillTaxonomyRelease",
]
