from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UUID,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class JobRelatedJobsSnapshot(Base):
    """Current AI-ranked Related Jobs result for one source Job."""

    __tablename__ = "job_related_jobs_snapshots"

    source_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_evidence_hash = Column(Text, nullable=False)
    model_provenance = Column(JSON, nullable=False, default=dict)
    completed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    items = relationship(
        "JobRelatedJobsSnapshotItem",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="JobRelatedJobsSnapshotItem.position",
        passive_deletes=True,
    )


class JobRelatedJobsSnapshotItem(Base):
    """One ordered target in a Job's current AI-ranked snapshot."""

    __tablename__ = "job_related_jobs_snapshot_items"
    __table_args__ = (
        UniqueConstraint(
            "source_job_id",
            "position",
            name="uq_job_related_jobs_snapshot_position",
        ),
    )

    source_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_related_jobs_snapshots.source_job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)

    snapshot = relationship("JobRelatedJobsSnapshot", back_populates="items")


__all__ = ["JobRelatedJobsSnapshot", "JobRelatedJobsSnapshotItem"]
