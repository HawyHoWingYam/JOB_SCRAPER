from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
import uuid


class ScrapeSchedule(Base):
    """Model for storing scheduled scraping tasks."""

    __tablename__ = "scrape_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Scheduling configuration
    cron_expression = Column(String(100), nullable=False)
    timezone = Column(String(50), default="Asia/Hong_Kong")
    source_site = Column(
        String(32),
        nullable=False,
        default="jobsdb",
        server_default=text("'jobsdb'"),
        index=True,
    )
    crawl_phase = Column(
        String(32),
        nullable=False,
        default="listing",
        server_default=text("'listing'"),
        index=True,
    )
    crawl_mode = Column(String(32), nullable=True)
    detail_limit = Column(Integer, nullable=False, default=100, server_default=text("100"))

    # Scraping parameters
    category_ids = Column(JSON, nullable=True)  # List of category IDs [1200, 6281, ...]
    keywords = Column(String(500), nullable=True)
    location = Column(String(255), default="Hong Kong")
    max_pages = Column(Integer, default=3)

    # Status
    is_active = Column(Boolean, default=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True, index=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    executions = relationship(
        "ScheduleExecution",
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="desc(ScheduleExecution.started_at)",
    )
    crawl_jobs = relationship("CrawlJob", back_populates="schedule")

    def __repr__(self):
        return f"<ScrapeSchedule(id={self.id}, name={self.name}, cron={self.cron_expression})>"


class ScheduleExecution(Base):
    """Model for tracking schedule execution history."""

    __tablename__ = "schedule_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crawl_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Execution details
    status = Column(String(50), nullable=False, default="pending", index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Results
    jobs_scraped = Column(Integer, default=0)
    jobs_saved = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    request_payload_snapshot = Column(JSON, nullable=True)

    # Phase completion tracking
    phase1_completed = Column(Boolean, default=False)
    phase2_completed = Column(Boolean, default=False)
    phase3_completed = Column(Boolean, default=False)
    phase4_completed = Column(Boolean, default=False)
    phase5_completed = Column(Boolean, default=False)

    # Detailed stats
    ids_collected = Column(Integer, default=0)
    jobs_classified = Column(Integer, default=0)

    # Timing
    phase1_duration = Column(Integer, default=0)
    phase2_duration = Column(Integer, default=0)
    phase3_duration = Column(Integer, default=0)
    phase4_duration = Column(Integer, default=0)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("ScrapeSchedule", back_populates="executions")
    crawl_job = relationship("CrawlJob", back_populates="schedule_executions")

    def __repr__(self):
        return f"<ScheduleExecution(id={self.id}, status={self.status})>"


class SchedulerRuntimeHeartbeat(Base):
    """Singleton row for scheduler-worker ownership and heartbeat status."""

    __tablename__ = "scheduler_runtime_heartbeats"

    id = Column(Integer, primary_key=True, default=1)
    owner = Column(String(64), nullable=False)
    worker_name = Column(String(255), nullable=True)
    started_at = Column(DateTime, nullable=False)
    last_heartbeat_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(50), nullable=False)
    active_schedule_count = Column(Integer, nullable=False, default=0)
    registered_job_count = Column(Integer, nullable=False, default=0)
    last_reconcile_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<SchedulerRuntimeHeartbeat(owner={self.owner}, worker_name={self.worker_name}, "
            f"status={self.status})>"
        )
