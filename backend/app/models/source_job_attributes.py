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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class JobSourceAttributeProjection(Base):
    __tablename__ = "job_source_attribute_projections"
    __table_args__ = (
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_attribute_projection_source",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_job_source_attribute_projection_hash",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_job_source_attribute_projection_version",
        ),
    )

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_site = Column(String(32), nullable=False, index=True)
    evidence_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    job = relationship("Job", back_populates="source_attribute_projection")


class EmploymentType(Base):
    __tablename__ = "employment_types"
    __table_args__ = (
        CheckConstraint(
            "sort_order > 0",
            name="ck_employment_type_sort_order",
        ),
    )

    code = Column(String(32), primary_key=True)
    label = Column(String(64), nullable=False, unique=True)
    sort_order = Column(Integer, nullable=False, unique=True)


class JobSourceClassificationPath(Base):
    __tablename__ = "job_source_classification_paths"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "source_site",
            name="uq_job_source_classification_path_id_source",
        ),
        UniqueConstraint(
            "job_id",
            "path_fingerprint",
            name="uq_job_source_classification_path_fingerprint",
        ),
        UniqueConstraint(
            "job_id",
            "source_order",
            name="uq_job_source_classification_path_order",
        ),
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_classification_path_source",
        ),
        CheckConstraint(
            "source_order >= 0",
            name="ck_job_source_classification_path_order",
        ),
        CheckConstraint(
            "length(path_fingerprint) = 64",
            name="ck_job_source_classification_path_fingerprint",
        ),
        CheckConstraint(
            "(is_primary AND primary_basis IS NOT NULL AND length(trim(primary_basis)) > 0) "
            "OR (NOT is_primary AND primary_basis IS NULL)",
            name="ck_job_source_classification_path_primary_basis",
        ),
        ForeignKeyConstraint(
            ["source_catalog_revision_id", "source_site"],
            ["source_catalog_revisions.id", "source_catalog_revisions.source_site"],
            name="fk_job_source_classification_path_catalog_source",
            ondelete="RESTRICT",
        ),
        Index(
            "ux_job_source_classification_primary",
            "job_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary = 1"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_site = Column(String(32), nullable=False, index=True)
    source_catalog_revision_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    source_order = Column(Integer, nullable=False)
    path_fingerprint = Column(String(64), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    primary_basis = Column(String(255), nullable=True)
    provenance = Column(JSON, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    nodes = relationship(
        "JobSourceClassificationPathNode",
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="JobSourceClassificationPathNode.source_position",
    )
    source_catalog_revision = relationship("SourceCatalogRevision")
    job = relationship("Job", back_populates="source_classification_paths")

    @property
    def catalog_revision(self) -> dict[str, str] | None:
        revision = self.source_catalog_revision
        if revision is None:
            return None
        return {
            "source_site": revision.source_site,
            "revision_id": str(revision.id),
            "fingerprint": revision.fingerprint,
        }

    @property
    def provenance_limited(self) -> bool:
        return self.source_catalog_revision_id is None


class JobSourceClassificationPathNode(Base):
    __tablename__ = "job_source_classification_path_nodes"
    __table_args__ = (
        UniqueConstraint(
            "path_id",
            "source_position",
            name="uq_job_source_classification_node_position",
        ),
        UniqueConstraint(
            "path_id",
            "source_classification_id",
            name="uq_job_source_classification_node_identity",
        ),
        ForeignKeyConstraint(
            ["path_id", "source_site"],
            [
                "job_source_classification_paths.id",
                "job_source_classification_paths.source_site",
            ],
            name="fk_job_source_classification_node_path_source",
            ondelete="CASCADE",
        ),
        Index(
            "ix_job_source_classification_node_source_identity",
            "source_site",
            "source_classification_id",
        ),
        CheckConstraint(
            "source_position >= 0",
            name="ck_job_source_classification_node_position",
        ),
        CheckConstraint(
            "native_depth >= 0",
            name="ck_job_source_classification_node_depth",
        ),
        CheckConstraint(
            "source_classification_id LIKE source_site || ':%' "
            "AND length(source_classification_id) > length(source_site) + 1",
            name="ck_job_source_classification_node_source_identity",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    path_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    source_site = Column(String(32), nullable=False)
    source_position = Column(Integer, nullable=False)
    native_depth = Column(Integer, nullable=False)
    source_classification_id = Column(String(255), nullable=False)
    native_id = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)

    path = relationship("JobSourceClassificationPath", back_populates="nodes")


class JobSourceEmploymentLabel(Base):
    __tablename__ = "job_source_employment_labels"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "source_order",
            name="uq_job_source_employment_label_order",
        ),
        CheckConstraint(
            "raw_code IS NOT NULL OR raw_label IS NOT NULL",
            name="ck_job_source_employment_label_evidence",
        ),
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_employment_label_source",
        ),
        CheckConstraint(
            "source_order >= 0",
            name="ck_job_source_employment_label_order",
        ),
        Index(
            "ix_job_source_employment_label_source_lookup",
            "source_site",
            "normalized_lookup_key",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_site = Column(String(32), nullable=False)
    source_order = Column(Integer, nullable=False)
    raw_code = Column(String(255), nullable=True)
    raw_label = Column(String(255), nullable=True)
    normalized_lookup_key = Column(String(255), nullable=True)
    mapped_type_code = Column(
        String(32),
        ForeignKey("employment_types.code", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    mapping_id = Column(String(255), nullable=True)
    provenance = Column(JSON, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    job = relationship("Job", back_populates="source_employment_labels")


class JobEmploymentType(Base):
    __tablename__ = "job_employment_types"

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    employment_type_code = Column(
        String(32),
        ForeignKey("employment_types.code", ondelete="RESTRICT"),
        primary_key=True,
    )
    evidence_label_ids = Column(JSON, nullable=False, default=list)
    provenance = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    employment_type = relationship("EmploymentType")
    job = relationship("Job", back_populates="employment_type_assignments")


SOURCE_JOB_ATTRIBUTE_TABLES = (
    JobSourceAttributeProjection.__table__,
    EmploymentType.__table__,
    JobSourceClassificationPath.__table__,
    JobSourceClassificationPathNode.__table__,
    JobSourceEmploymentLabel.__table__,
    JobEmploymentType.__table__,
)
