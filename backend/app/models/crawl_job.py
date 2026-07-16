from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class CrawlJob(Base):
    """Durable control-plane record for a crawl request."""

    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index(
            "ix_crawl_jobs_status_queued_created",
            "status",
            "queued_at",
            "created_at",
        ),
        Index(
            "ix_crawl_jobs_queued_created",
            "queued_at",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    source_site = Column(String(32), nullable=False, index=True)
    trigger_type = Column(String(32), nullable=False)
    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(32), nullable=False, default="queued", index=True)
    request_payload = Column(JSON, nullable=False)
    requested_by = Column(String(255), nullable=True)
    queued_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    metrics = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    schedule = relationship("ScrapeSchedule", back_populates="crawl_jobs")
    events = relationship(
        "CrawlJobEvent",
        back_populates="crawl_job",
        cascade="all, delete-orphan",
        order_by="asc(CrawlJobEvent.sequence_no)",
    )
    schedule_executions = relationship("ScheduleExecution", back_populates="crawl_job")
    crawl_runs = relationship("CrawlRun", back_populates="crawl_job", lazy="selectin")
    executions = relationship(
        "CrawlJobExecution",
        back_populates="crawl_job",
        cascade="all, delete-orphan",
        order_by="asc(CrawlJobExecution.created_at)",
    )


class CrawlJobEvent(Base):
    """Ordered event history for a crawl job."""

    __tablename__ = "crawl_job_events"
    __table_args__ = (
        UniqueConstraint("crawl_job_id", "sequence_no", name="uq_crawl_job_events_job_sequence"),
        Index(
            "ix_crawl_job_events_job_event_sequence",
            "crawl_job_id",
            "event_type",
            "sequence_no",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    crawl_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_no = Column(Integer, nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    emitted_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    crawl_job = relationship("CrawlJob", back_populates="events")
