from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class CrawlJobExecution(Base):
    """Durable ownership for one locally launched CrawlJob process generation."""

    __tablename__ = "crawl_job_executions"
    __table_args__ = (
        Index(
            "ix_crawl_job_executions_job_status_created",
            "crawl_job_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_crawl_job_executions_status_stop_requested",
            "status",
            "stop_requested_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    launcher_instance_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="launching", index=True)
    pid = Column(Integer, nullable=True)
    process_create_time = Column(Float, nullable=True)
    command = Column(JSON, nullable=False, default=list)
    launched_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    stop_requested_at = Column(DateTime(timezone=True), nullable=True)
    exited_at = Column(DateTime(timezone=True), nullable=True)
    exit_code = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    crawl_job = relationship("CrawlJob", back_populates="executions")
