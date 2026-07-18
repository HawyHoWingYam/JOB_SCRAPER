from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import relationship

from app.database import Base


class EnrichmentRun(Base):
    """Tracks a persisted enrichment orchestration run."""

    __tablename__ = "enrichment_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_type = Column(String(50), nullable=False, index=True)
    trigger_crawl_job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(32), nullable=False, default="pending", index=True)
    job_ids = Column(JSON, nullable=False)
    total_items = Column(Integer, nullable=False)
    pending_items = Column(Integer, nullable=False)
    completed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    cancelled_items = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    stop_requested_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    current_job_title = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    items = relationship(
        "EnrichmentRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EnrichmentRunItem.position",
    )


class EnrichmentRunItem(Base):
    """Tracks each item in an enrichment run."""

    __tablename__ = "enrichment_run_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(
        String(36),
        ForeignKey("enrichment_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    run = relationship("EnrichmentRun", back_populates="items")
