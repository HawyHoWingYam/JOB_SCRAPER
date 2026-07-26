from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class SourceClassification(Base):
    """Current Source-qualified classification identity, without releases."""

    __tablename__ = "source_classifications"
    __table_args__ = (
        UniqueConstraint(
            "source_site",
            "classification_id",
            name="uq_source_classification_source_identity",
        ),
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_source_classification_source",
        ),
        CheckConstraint("depth >= 0", name="ck_source_classification_depth"),
        CheckConstraint(
            "classification_id LIKE source_site || ':%' "
            "AND length(classification_id) > length(source_site) + 1",
            name="ck_source_classification_identity",
        ),
        CheckConstraint(
            "(depth = 0 AND is_top_level) OR (depth > 0 AND NOT is_top_level)",
            name="ck_source_classification_top_level",
        ),
        Index(
            "ix_source_classification_active_roots",
            "source_site",
            "is_active",
            "is_top_level",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_site = Column(String(32), nullable=False)
    classification_id = Column(String(255), nullable=False)
    native_id = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_classifications.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    depth = Column(Integer, nullable=False)
    is_top_level = Column(Boolean, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    query_metadata = Column(JSON, nullable=False, default=dict)
    first_observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_observed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    parent = relationship("SourceClassification", remote_side=[id])


SOURCE_CLASSIFICATION_TABLES = (SourceClassification.__table__,)
