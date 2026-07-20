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
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class CrawlDispatchPlan(Base):
    """Immutable reviewed execution authority with a single-use lifecycle."""

    __tablename__ = "crawl_dispatch_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["catalog_revision_id", "source_site"],
            [
                "source_catalog_revisions.id",
                "source_catalog_revisions.source_site",
            ],
            name="fk_crawl_dispatch_plans_catalog_revision_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "plan_fingerprint",
            name="uq_crawl_dispatch_plans_fingerprint",
        ),
        UniqueConstraint(
            "crawl_job_id",
            name="uq_crawl_dispatch_plans_crawl_job_id",
        ),
        CheckConstraint(
            "state IN ('prepared', 'consumed', 'expired')",
            name="ck_crawl_dispatch_plans_state",
        ),
        CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_crawl_dispatch_plans_source_site",
        ),
        CheckConstraint(
            "crawl_phase IN ('listing', 'detail')",
            name="ck_crawl_dispatch_plans_crawl_phase",
        ),
        CheckConstraint(
            "trigger_kind IN ('one_off', 'saved_automation', "
            "'scheduled_automation')",
            name="ck_crawl_dispatch_plans_trigger_kind",
        ),
        CheckConstraint(
            "(trigger_kind = 'one_off' AND automation_id IS NULL "
            "AND automation_id_snapshot IS NULL "
            "AND expected_automation_revision IS NULL) OR "
            "(trigger_kind IN ('saved_automation', 'scheduled_automation') "
            "AND automation_id_snapshot IS NOT NULL "
            "AND expected_automation_revision > 0)",
            name="ck_crawl_dispatch_plans_automation_shape",
        ),
        CheckConstraint(
            "(crawl_phase = 'listing' AND listing_settings IS NOT NULL "
            "AND detail_settings IS NULL AND detail_target_count = 0) OR "
            "(crawl_phase = 'detail' AND listing_settings IS NULL "
            "AND detail_settings IS NOT NULL AND detail_target_count >= 0)",
            name="ck_crawl_dispatch_plans_execution_settings",
        ),
        CheckConstraint(
            "length(plan_fingerprint) = 64",
            name="ck_crawl_dispatch_plans_fingerprint",
        ),
        CheckConstraint(
            "(confirmation_required AND confirmation_token_hash IS NOT NULL "
            "AND length(confirmation_token_hash) = 64) "
            "OR (NOT confirmation_required AND "
            "confirmation_token_hash IS NULL)",
            name="ck_crawl_dispatch_plans_confirmation_hash",
        ),
        CheckConstraint(
            "expires_at > prepared_at",
            name="ck_crawl_dispatch_plans_expiry",
        ),
        CheckConstraint(
            "(state = 'prepared' AND consumed_at IS NULL AND crawl_job_id IS NULL) "
            "OR (state = 'consumed' AND consumed_at IS NOT NULL "
            "AND crawl_job_id IS NOT NULL) "
            "OR (state = 'expired' AND consumed_at IS NULL AND crawl_job_id IS NULL)",
            name="ck_crawl_dispatch_plans_state_shape",
        ),
        Index(
            "ix_crawl_dispatch_plans_state_expiry",
            "state",
            "expires_at",
        ),
        Index(
            "ix_crawl_dispatch_plans_automation_revision",
            "automation_id",
            "expected_automation_revision",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state = Column(String(32), nullable=False, default="prepared", index=True)
    source_site = Column(String(32), nullable=False, index=True)
    crawl_phase = Column(String(32), nullable=False, index=True)
    trigger_kind = Column(String(32), nullable=False)
    automation_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "scrape_schedules.id",
            name="fk_crawl_dispatch_plans_automation_id_scrape_schedules",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    automation_id_snapshot = Column(UUID(as_uuid=True), nullable=True, index=True)
    expected_automation_revision = Column(Integer, nullable=True)
    catalog_revision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    authored_scope = Column(JSON, nullable=False)
    resolved_scope = Column(JSON, nullable=False)
    listing_settings = Column(JSON(none_as_null=True), nullable=True)
    detail_settings = Column(JSON(none_as_null=True), nullable=True)
    readiness = Column(JSON, nullable=False)
    detail_target_count = Column(Integer, nullable=False, default=0)
    plan_fingerprint = Column(String(64), nullable=False)
    confirmation_required = Column(Boolean, nullable=False)
    confirmation_token_hash = Column(String(64), nullable=True)
    prepared_by = Column(String(255), nullable=False)
    prepared_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    crawl_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "crawl_jobs.id",
            name="fk_crawl_dispatch_plans_crawl_job_id_crawl_jobs",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )

    automation = relationship("ScrapeSchedule")
    crawl_job = relationship(
        "CrawlJob",
        foreign_keys=[crawl_job_id],
        uselist=False,
        post_update=True,
    )
    targets = relationship(
        "CrawlDispatchPlanTarget",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CrawlDispatchPlanTarget.selection_order",
    )


class CrawlDispatchPlanTarget(Base):
    """One deterministic canonical detail identity selected into a plan."""

    __tablename__ = "crawl_dispatch_plan_targets"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "source_site",
            "source_job_id",
            name="uq_crawl_dispatch_plan_targets_identity",
        ),
        UniqueConstraint(
            "plan_id",
            "selection_order",
            name="uq_crawl_dispatch_plan_targets_order",
        ),
        CheckConstraint(
            "selection_order >= 0 AND length(eligibility_fingerprint) = 64",
            name="ck_crawl_dispatch_plan_targets_selection",
        ),
        Index(
            "ix_crawl_dispatch_plan_targets_source_job",
            "source_site",
            "source_job_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "crawl_dispatch_plans.id",
            name="fk_crawl_dispatch_plan_targets_plan_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    source_site = Column(String(32), nullable=False)
    source_job_id = Column(String(255), nullable=False)
    selection_order = Column(Integer, nullable=False)
    eligibility_fingerprint = Column(String(64), nullable=False)
    eligibility_status = Column(String(32), nullable=False)
    status_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    plan = relationship("CrawlDispatchPlan", back_populates="targets")
    rows = relationship(
        "CrawlDispatchPlanTargetRow",
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CrawlDispatchPlanTargetRow.row_order",
    )


class CrawlDispatchPlanTargetRow(Base):
    """Frozen staging-row membership contributing to a canonical target."""

    __tablename__ = "crawl_dispatch_plan_target_rows"
    __table_args__ = (
        UniqueConstraint(
            "plan_target_id",
            "crawl_job_listing_id",
            name="uq_crawl_dispatch_plan_target_rows_membership",
        ),
        UniqueConstraint(
            "plan_target_id",
            "row_order",
            name="uq_crawl_dispatch_plan_target_rows_order",
        ),
        CheckConstraint(
            "row_order >= 0 AND length(eligibility_fingerprint) = 64",
            name="ck_crawl_dispatch_plan_target_rows_selection",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_target_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "crawl_dispatch_plan_targets.id",
            name="fk_crawl_dispatch_plan_target_rows_plan_target_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    crawl_job_listing_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "crawl_job_listings.id",
            name="fk_crawl_dispatch_plan_target_rows_listing_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    row_order = Column(Integer, nullable=False)
    eligibility_fingerprint = Column(String(64), nullable=False)
    eligibility_status = Column(String(32), nullable=False)
    status_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    target = relationship("CrawlDispatchPlanTarget", back_populates="rows")
    listing_row = relationship("CrawlJobListing")


_PLAN_IMMUTABLE_FIELDS = (
    "source_site",
    "crawl_phase",
    "trigger_kind",
    "automation_id",
    "automation_id_snapshot",
    "expected_automation_revision",
    "catalog_revision_id",
    "authored_scope",
    "resolved_scope",
    "listing_settings",
    "detail_settings",
    "readiness",
    "detail_target_count",
    "plan_fingerprint",
    "confirmation_required",
    "confirmation_token_hash",
    "prepared_by",
    "prepared_at",
    "expires_at",
)

_PLAN_LIFECYCLE_FIELDS = {"state", "consumed_at", "crawl_job_id"}


@event.listens_for(CrawlDispatchPlan, "before_update")
def _guard_dispatch_plan_update(_mapper, _connection, plan) -> None:
    state = inspect(plan)
    if any(state.attrs[field].history.has_changes() for field in _PLAN_IMMUTABLE_FIELDS):
        raise ValueError("Dispatch Plan reviewed content is immutable")
    changed_fields = {
        field
        for field in _PLAN_LIFECYCLE_FIELDS
        if state.attrs[field].history.has_changes()
    }
    state_history = state.attrs.state.history
    if not state_history.has_changes():
        raise ValueError("Dispatch Plan updates require one lifecycle transition")
    previous = state_history.deleted[0]
    current = state_history.added[0]
    if previous != "prepared" or current not in {"consumed", "expired"}:
        raise ValueError("Dispatch Plan lifecycle transition is invalid")
    if current == "consumed":
        if changed_fields != _PLAN_LIFECYCLE_FIELDS:
            raise ValueError(
                "Consuming a Dispatch Plan requires one Crawl Job and timestamp"
            )
        if plan.crawl_job_id is None or plan.consumed_at is None:
            raise ValueError(
                "Consumed Dispatch Plan requires one Crawl Job and timestamp"
            )
    elif changed_fields != {"state"}:
        raise ValueError("Expiring a Dispatch Plan cannot attach a Crawl Job")


@event.listens_for(CrawlDispatchPlan, "before_delete")
def _guard_dispatch_plan_delete(_mapper, _connection, plan) -> None:
    if plan.state != "expired":
        raise ValueError("Only expired unconsumed Dispatch Plans may be deleted")


@event.listens_for(CrawlDispatchPlanTarget, "before_update")
def _prevent_dispatch_plan_target_update(_mapper, _connection, _target) -> None:
    raise ValueError("Dispatch Plan targets are immutable")


@event.listens_for(CrawlDispatchPlanTarget, "before_delete")
def _prevent_dispatch_plan_target_delete(_mapper, _connection, _target) -> None:
    raise ValueError("Dispatch Plan targets are immutable")


@event.listens_for(CrawlDispatchPlanTargetRow, "before_update")
def _prevent_dispatch_plan_target_row_update(_mapper, _connection, _row) -> None:
    raise ValueError("Dispatch Plan target rows are immutable")


@event.listens_for(CrawlDispatchPlanTargetRow, "before_delete")
def _prevent_dispatch_plan_target_row_delete(_mapper, _connection, _row) -> None:
    raise ValueError("Dispatch Plan target rows are immutable")


CRAWL_DISPATCH_PLAN_TABLES = (
    CrawlDispatchPlan.__table__,
    CrawlDispatchPlanTarget.__table__,
    CrawlDispatchPlanTargetRow.__table__,
)
