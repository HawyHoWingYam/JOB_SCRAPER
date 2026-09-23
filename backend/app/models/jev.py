from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    Index,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class JevRuntimeSettings(Base):
    """Singleton future-run defaults and cumulative allowance for Jev work."""

    __tablename__ = "jev_runtime_settings"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    endpoint = Column(String(512), nullable=False)
    model = Column(String(255), nullable=False)
    api_key = Column(Text, nullable=True)
    allowance_microdollars = Column(Integer, nullable=False)
    spent_microdollars = Column(Integer, nullable=False, default=0)
    reserved_microdollars = Column(Integer, nullable=False, default=0)
    input_microdollars_per_million_tokens = Column(Integer, nullable=True)
    output_microdollars_per_million_tokens = Column(Integer, nullable=True)
    max_request_reservation_microdollars = Column(Integer, nullable=True)
    sample_limit = Column(Integer, nullable=False)
    question_batch_limit = Column(Integer, nullable=False)
    concurrency = Column(Integer, nullable=False)
    retry_limit = Column(Integer, nullable=False)
    timeout_seconds = Column(Integer, nullable=False)
    evidence_threshold_millis = Column(Integer, nullable=False)
    recommendation_threshold_millis = Column(Integer, nullable=False)
    duplicate_enabled = Column(Boolean, nullable=False, default=False)
    duplicate_candidate_limit = Column(Integer, nullable=False, default=3)
    duplicate_corpus_limit = Column(Integer, nullable=False, default=200)
    crawl_quality_enabled = Column(Boolean, nullable=False, default=False)
    crawl_quality_batch_limit = Column(Integer, nullable=False, default=20)
    search_rerank_enabled = Column(Boolean, nullable=False, default=False)
    search_rerank_candidate_limit = Column(Integer, nullable=False, default=20)
    incident_triage_enabled = Column(Boolean, nullable=False, default=False)
    incident_triage_event_limit = Column(Integer, nullable=False, default=200)
    maintenance_enabled = Column(Boolean, nullable=False, default=False)
    maintenance_model = Column(String(255), nullable=False, default="jev-latest")
    maintenance_allowance_microdollars = Column(
        Integer, nullable=False, default=2_000_000
    )
    maintenance_spent_microdollars = Column(Integer, nullable=False, default=0)
    maintenance_reserved_microdollars = Column(Integer, nullable=False, default=0)
    maintenance_interval_days = Column(Integer, nullable=False, default=30)
    maintenance_min_candidates = Column(Integer, nullable=False, default=50)
    maintenance_batch_size = Column(Integer, nullable=False, default=100)
    maintenance_threshold_millis = Column(Integer, nullable=False, default=900)
    maintenance_last_checked_at = Column(DateTime, nullable=True)
    maintenance_last_started_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class JevBudgetReservation(Base):
    """One auditable pre-dispatch claim against the cumulative Jev allowance."""

    __tablename__ = "jev_budget_reservations"
    __table_args__ = (
        UniqueConstraint("attempt_key", name="uq_jev_budget_reservation_attempt"),
        CheckConstraint(
            "reserved_microdollars > 0",
            name="ck_jev_budget_reservation_positive",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    settings_id = Column(
        Integer,
        ForeignKey("jev_runtime_settings.id", ondelete="RESTRICT"),
        nullable=False,
        default=1,
    )
    attempt_key = Column(String(255), nullable=False)
    budget_scope = Column(String(32), nullable=False, default="online")
    status = Column(String(32), nullable=False, default="reserved", index=True)
    reserved_microdollars = Column(Integer, nullable=False)
    actual_microdollars = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    settled_at = Column(DateTime, nullable=True)


class JevRun(Base):
    """One bounded Jev run with frozen non-secret configuration and work."""

    __tablename__ = "jev_runs"
    __table_args__ = (
        Index(
            "ux_jev_run_active_purpose",
            "purpose",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'stopping')"),
            sqlite_where=text("status IN ('pending', 'running', 'stopping')"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    purpose = Column(String(64), nullable=False, index=True)
    rubric_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    settings_snapshot = Column(JSON, nullable=False)
    total_items = Column(Integer, nullable=False)
    pending_items = Column(Integer, nullable=False)
    running_items = Column(Integer, nullable=False, default=0)
    completed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    cancelled_items = Column(Integer, nullable=False, default=0)
    stop_requested_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)

    items = relationship(
        "JevRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="JevRunItem.position",
    )


class JevRunItem(Base):
    """One immutable subject payload within a bounded Jev run."""

    __tablename__ = "jev_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "subject_id", name="uq_jev_run_item_subject"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id = Column(String(255), nullable=False)
    position = Column(Integer, nullable=False)
    evidence_refs = Column(JSON, nullable=False, default=list)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    run = relationship("JevRun", back_populates="items")
    attempts = relationship(
        "JevRunAttempt",
        cascade="all, delete-orphan",
        order_by="JevRunAttempt.attempt_number",
    )


class JevRunAttempt(Base):
    """Immutable receipt for one budgeted external attempt."""

    __tablename__ = "jev_run_attempts"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "attempt_number",
            name="uq_jev_run_attempt_number",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id = Column(
        String(36),
        ForeignKey("jev_run_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reservation_id = Column(
        String(36),
        ForeignKey("jev_budget_reservations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    model = Column(String(255), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    reserved_microdollars = Column(Integer, nullable=False)
    actual_microdollars = Column(Integer, nullable=True)
    result = Column(JSON, nullable=True)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)


class JevOnlineSkillClassification(Base):
    """Idempotent Job-level audit record for online Jev Skill classification."""

    __tablename__ = "jev_online_skill_classifications"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "input_fingerprint",
            name="uq_jev_online_skill_job_input",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'answered', 'unavailable', 'invalid')",
            name="ck_jev_online_skill_status",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    input_fingerprint = Column(String(64), nullable=False)
    taxonomy_snapshot_sha256 = Column(String(64), nullable=False)
    rubric_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    apply_projection = Column(Boolean, nullable=False, default=False)
    evidence_snapshot = Column(JSON, nullable=False)
    decisions = Column(JSON, nullable=True)
    receipt = Column(JSON, nullable=True)
    receipt_history = Column(JSON, nullable=False, default=list)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class JevSkillMaintenanceBatch(Base):
    """One frozen stronger-model review over accumulated Skill exceptions."""

    __tablename__ = "jev_skill_maintenance_batches"
    __table_args__ = (
        Index(
            "ux_jev_skill_maintenance_active",
            text("(1)"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    status = Column(String(32), nullable=False, default="pending", index=True)
    trigger = Column(String(32), nullable=False)
    eligible_count = Column(Integer, nullable=False)
    candidate_ids = Column(JSON, nullable=False)
    settings_snapshot = Column(JSON, nullable=False)
    taxonomy_snapshot_sha256 = Column(String(64), nullable=False)
    proposals = Column(JSON, nullable=False, default=list)
    applied_changes = Column(JSON, nullable=False, default=list)
    receipt = Column(JSON, nullable=True)
    auto_applied_count = Column(Integer, nullable=False, default=0)
    held_for_approval_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class JevDuplicateAssociation(Base):
    """Source-preserving Jev judgment for one immutable Job evidence pair."""

    __tablename__ = "jev_duplicate_associations"
    __table_args__ = (
        UniqueConstraint(
            "pair_key",
            "input_fingerprint",
            name="uq_jev_duplicate_pair_input",
        ),
        CheckConstraint(
            "left_job_id <> right_job_id",
            name="ck_jev_duplicate_distinct_jobs",
        ),
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'rejected', 'insufficient', "
            "'unavailable', 'invalid', 'superseded')",
            name="ck_jev_duplicate_status",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pair_key = Column(String(64), nullable=False, index=True)
    input_fingerprint = Column(String(64), nullable=False)
    left_job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    right_job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    left_source_identity = Column(String(320), nullable=False)
    right_source_identity = Column(String(320), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    confidence_millis = Column(Integer, nullable=True)
    candidate_provenance = Column(JSON, nullable=False, default=dict)
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    jev_run_item_id = Column(
        String(36),
        ForeignKey("jev_run_items.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    receipt = Column(JSON, nullable=True)
    error_code = Column(String(128), nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class JevCrawlQualityEvaluation(Base):
    """One bounded, non-mutating quality review for a Crawl Job snapshot."""

    __tablename__ = "jev_crawl_quality_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "crawl_job_id",
            "input_fingerprint",
            name="uq_jev_crawl_quality_job_input",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    crawl_job_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    input_fingerprint = Column(String(64), nullable=False)
    rubric_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    selected_listing_ids = Column(JSON, nullable=False)
    eligible_count = Column(Integer, nullable=False)
    excluded_count = Column(Integer, nullable=False)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)


class JevCrawlQualityObservation(Base):
    """Immutable terminal advisory for one listing quality evaluation."""

    __tablename__ = "jev_crawl_quality_observations"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "crawl_job_listing_id",
            name="uq_jev_crawl_quality_evaluation_listing",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id = Column(
        String(36),
        ForeignKey("jev_crawl_quality_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    crawl_job_listing_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("crawl_job_listings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_identity = Column(String(320), nullable=False)
    evidence_sha256 = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    quality = Column(String(64), nullable=True)
    problem_kind = Column(String(64), nullable=True)
    probabilities = Column(JSON, nullable=False, default=dict)
    receipt = Column(JSON, nullable=True)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)


class JevSearchRerankEvaluation(Base):
    """Frozen lexical candidate prefix and its advisory Jev order."""

    __tablename__ = "jev_search_rerank_evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    scope_fingerprint = Column(String(64), nullable=False, index=True)
    scope_snapshot = Column(JSON, nullable=False)
    retrieval_mode = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    eligible_count = Column(Integer, nullable=False)
    baseline_job_ids = Column(JSON, nullable=False)
    ordered_job_ids = Column(JSON, nullable=False)
    candidate_snapshots = Column(JSON, nullable=False)
    facets_snapshot = Column(JSON, nullable=False)
    receipt = Column(JSON, nullable=True)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)


class JevIncidentTriageEvaluation(Base):
    """Frozen, secret-safe repeated-incident snapshot and advisory receipt."""

    __tablename__ = "jev_incident_triage_evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    jev_run_id = Column(
        String(36),
        ForeignKey("jev_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    input_fingerprint = Column(String(64), nullable=False, unique=True)
    rubric_version = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    event_limit = Column(Integer, nullable=False)
    total_event_count = Column(Integer, nullable=False)
    eligible_cluster_count = Column(Integer, nullable=False)
    selected_cluster_ids = Column(JSON, nullable=False)
    receipt = Column(JSON, nullable=True)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)


class JevIncidentTriageCluster(Base):
    """Immutable event membership plus an optional non-authoritative Jev advice."""

    __tablename__ = "jev_incident_triage_clusters"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "cluster_id",
            name="uq_jev_incident_evaluation_cluster",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id = Column(
        String(36),
        ForeignKey("jev_incident_triage_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cluster_id = Column(String(64), nullable=False)
    source_site = Column(String(32), nullable=False)
    phase = Column(String(100), nullable=False)
    issue_class = Column(String(100), nullable=False)
    issue_code = Column(String(100), nullable=True)
    issue_stage = Column(String(100), nullable=True)
    normalized_symptom = Column(String(500), nullable=False)
    event_refs = Column(JSON, nullable=False)
    event_count = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="preview")
    disposition = Column(String(100), nullable=True)
    probabilities = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)


__all__ = [
    "JevBudgetReservation",
    "JevCrawlQualityEvaluation",
    "JevCrawlQualityObservation",
    "JevDuplicateAssociation",
    "JevIncidentTriageCluster",
    "JevIncidentTriageEvaluation",
    "JevOnlineSkillClassification",
    "JevRun",
    "JevRunAttempt",
    "JevRunItem",
    "JevRuntimeSettings",
    "JevSearchRerankEvaluation",
    "JevSkillMaintenanceBatch",
]
