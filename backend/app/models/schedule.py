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
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


AUTOMATION_LIFECYCLE_STATES = (
    "active",
    "paused",
    "archived",
    "scope_review_required",
)


class ScrapeSchedule(Base):
    """Model for storing scheduled scraping tasks."""

    __tablename__ = "scrape_schedules"
    __table_args__ = (
        CheckConstraint(
            "revision > 0",
            name="ck_scrape_schedules_revision_positive",
        ),
        CheckConstraint(
            "lifecycle_state IN ('active', 'paused', 'archived', "
            "'scope_review_required')",
            name="ck_scrape_schedules_lifecycle_state",
        ),
        CheckConstraint(
            "(lifecycle_state = 'archived' AND archived_at IS NOT NULL) OR "
            "(lifecycle_state <> 'archived' AND archived_at IS NULL)",
            name="ck_scrape_schedules_archived_at",
        ),
        Index(
            "ix_scrape_schedules_lifecycle_next_run",
            "lifecycle_state",
            "next_run_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Scheduling configuration
    cron_expression = Column(String(100), nullable=False)
    timezone = Column(
        String(50),
        nullable=False,
        default="Asia/Hong_Kong",
        server_default=text("'Asia/Hong_Kong'"),
    )
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
    location = Column(String(255), nullable=True)
    max_pages = Column(Integer, default=3)

    # Versioned Automation authority. Legacy primitive columns above remain
    # compatibility projections until the approved Crawl Control cutover.
    revision = Column(Integer, nullable=False, default=1, server_default=text("1"))
    lifecycle_state = Column(
        String(32),
        nullable=False,
        default="paused",
        server_default=text("'paused'"),
        index=True,
    )
    scope_contract = Column(JSON, nullable=True)
    listing_page_depth = Column(Integer, nullable=True)
    listing_run_page_cap = Column(Integer, nullable=True)
    detail_run_cap = Column(Integer, nullable=True)
    detail_limit_kind = Column(String(32), nullable=True)
    detail_backlog_scope = Column(JSON, nullable=True)
    scope_review_reason = Column(JSON, nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        index=True,
    )
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Metadata
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationships
    executions = relationship(
        "ScheduleExecution",
        back_populates="schedule",
        order_by="desc(ScheduleExecution.started_at)",
        passive_deletes=True,
    )
    crawl_jobs = relationship("CrawlJob", back_populates="schedule")
    automation_revisions = relationship(
        "AutomationRevision",
        back_populates="automation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AutomationRevision.revision",
    )

    def __repr__(self):
        return f"<ScrapeSchedule(id={self.id}, name={self.name}, cron={self.cron_expression})>"


class AutomationRevision(Base):
    """Immutable audit snapshot for one Automation revision."""

    __tablename__ = "automation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "revision",
            name="uq_automation_revisions_automation_revision",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_automation_revisions_revision_positive",
        ),
        CheckConstraint(
            "length(snapshot_fingerprint) = 64",
            name="ck_automation_revisions_snapshot_fingerprint",
        ),
        Index(
            "ix_automation_revisions_automation_created",
            "automation_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    snapshot_fingerprint = Column(String(64), nullable=False)
    operation = Column(String(64), nullable=False)
    actor = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    automation = relationship("ScrapeSchedule", back_populates="automation_revisions")


class AutomationDeleteReview(Base):
    """Expiring actor/revision-bound review for permanent Automation deletion."""

    __tablename__ = "automation_delete_reviews"
    __table_args__ = (
        CheckConstraint(
            "expected_revision > 0",
            name="ck_automation_delete_reviews_revision_positive",
        ),
        CheckConstraint(
            "length(token_hash) = 64 AND length(impact_fingerprint) = 64",
            name="ck_automation_delete_reviews_hashes",
        ),
        Index(
            "ix_automation_delete_reviews_automation_expiry",
            "automation_id_snapshot",
            "expires_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    automation_id_snapshot = Column(UUID(as_uuid=True), nullable=False)
    expected_revision = Column(Integer, nullable=False)
    actor = Column(String(255), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    impact_fingerprint = Column(String(64), nullable=False)
    impact_snapshot = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class ScheduleExecution(Base):
    """Model for tracking schedule execution history."""

    __tablename__ = "schedule_executions"
    __table_args__ = (
        UniqueConstraint(
            "dispatch_plan_id",
            name="uq_schedule_executions_dispatch_plan_id",
        ),
        CheckConstraint(
            "(dispatch_plan_id IS NULL AND dispatch_plan_fingerprint IS NULL) "
            "OR (dispatch_plan_id IS NOT NULL AND "
            "dispatch_plan_fingerprint IS NOT NULL AND "
            "length(dispatch_plan_fingerprint) = 64)",
            name="ck_schedule_executions_dispatch_plan_link",
        ),
        Index(
            "ix_schedule_executions_schedule_started",
            "schedule_id",
            "started_at",
        ),
        Index(
            "ix_schedule_executions_crawl_job_started_created",
            "crawl_job_id",
            "started_at",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_schedules.id", ondelete="SET NULL"),
        nullable=True,
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
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Results
    jobs_scraped = Column(Integer, default=0)
    jobs_saved = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    request_payload_snapshot = Column(JSON, nullable=True)
    automation_id_snapshot = Column(UUID(as_uuid=True), nullable=True, index=True)
    automation_revision = Column(Integer, nullable=True)
    automation_snapshot = Column(JSON, nullable=True)
    dispatch_plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "crawl_dispatch_plans.id",
            name=(
                "fk_schedule_executions_dispatch_plan_id_"
                "crawl_dispatch_plans"
            ),
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    dispatch_plan_fingerprint = Column(String(64), nullable=True)

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
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    # Relationships
    schedule = relationship("ScrapeSchedule", back_populates="executions")
    crawl_job = relationship("CrawlJob", back_populates="schedule_executions")
    dispatch_plan = relationship(
        "CrawlDispatchPlan",
        foreign_keys=[dispatch_plan_id],
    )

    def __repr__(self):
        return f"<ScheduleExecution(id={self.id}, status={self.status})>"


class SchedulerRuntimeHeartbeat(Base):
    """Singleton row for scheduler-worker ownership and heartbeat status."""

    __tablename__ = "scheduler_runtime_heartbeats"

    id = Column(Integer, primary_key=True, default=1)
    owner = Column(String(64), nullable=False)
    worker_name = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(50), nullable=False)
    active_schedule_count = Column(Integer, nullable=False, default=0)
    registered_job_count = Column(Integer, nullable=False, default=0)
    last_reconcile_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<SchedulerRuntimeHeartbeat(owner={self.owner}, worker_name={self.worker_name}, "
            f"status={self.status})>"
        )


@event.listens_for(AutomationRevision, "before_update")
def _prevent_automation_revision_update(_mapper, _connection, _revision) -> None:
    raise ValueError("Automation revisions are immutable")


@event.listens_for(ScheduleExecution, "before_update")
def _prevent_schedule_execution_dispatch_plan_update(
    _mapper,
    _connection,
    execution,
) -> None:
    state = inspect(execution)
    if any(
        state.attrs[field].history.has_changes()
        for field in ("dispatch_plan_id", "dispatch_plan_fingerprint")
    ):
        raise ValueError("Schedule Execution Dispatch Plan authority is immutable")


AUTOMATION_CONTROL_TABLES = (
    ScrapeSchedule.__table__,
    AutomationRevision.__table__,
    AutomationDeleteReview.__table__,
    ScheduleExecution.__table__,
    SchedulerRuntimeHeartbeat.__table__,
)
