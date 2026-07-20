from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    FrozenContract,
    ResolvedRunScopeV1,
    SHA256_PATTERN,
    SourceSite,
    CrawlScopeErrorPayloadV1,
)
from app.crawl_control.automation_contracts import (
    AutomationLifecycleState,
    AutomationProjectionV1,
)
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanReadinessV1,
    DispatchPlanState,
)


class RunAuthorityProjectionV1(FrozenContract):
    version: Literal[1] = 1
    authority_kind: Literal["dispatch_plan", "legacy"]
    dispatch_plan_id: UUID | None = None
    dispatch_plan_fingerprint: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    plan_state: DispatchPlanState | None = None
    catalog_revision_id: UUID | None = None
    automation_id: UUID | None = None
    automation_revision: int | None = Field(default=None, ge=1)
    authored_scope: AuthoredCrawlScopeV1 | None = None
    resolved_scope: ResolvedRunScopeV1 | None = None
    readiness: DispatchPlanReadinessV1 | None = None

    @model_validator(mode="after")
    def validate_authority_shape(self) -> RunAuthorityProjectionV1:
        plan_fields = (
            self.dispatch_plan_id,
            self.dispatch_plan_fingerprint,
            self.plan_state,
            self.catalog_revision_id,
            self.authored_scope,
            self.resolved_scope,
            self.readiness,
        )
        automation_fields = (
            self.automation_id,
            self.automation_revision,
        )
        if self.authority_kind == "dispatch_plan":
            if any(value is None for value in plan_fields):
                raise ValueError(
                    "Dispatch Plan authority requires its immutable plan fields"
                )
            if (self.automation_id is None) != (self.automation_revision is None):
                raise ValueError(
                    "Dispatch Plan Automation authority requires both ID and revision"
                )
        elif any(value is not None for value in (*plan_fields, *automation_fields)):
            raise ValueError(
                "Legacy authority cannot claim Dispatch Plan or Automation fields"
            )
        return self


class ListingWorkloadProjectionV1(FrozenContract):
    version: Literal[1] = 1
    query_target_count: int = Field(ge=1)
    page_depth: int = Field(ge=1)
    estimated_max_pages: int = Field(ge=1)
    run_page_cap: int = Field(ge=1)
    pages_requested: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_workload_math(self) -> ListingWorkloadProjectionV1:
        if self.estimated_max_pages != self.query_target_count * self.page_depth:
            raise ValueError("Listing workload estimate is inconsistent")
        return self


class DetailSnapshotProjectionV1(FrozenContract):
    version: Literal[1] = 1
    backlog_scope: dict[str, Any]
    limit_kind: Literal["entire_snapshot", "stop_after", "legacy"]
    cutoff_at: datetime | None = None
    target_count: int = Field(ge=0)
    fetched_count: int = Field(ge=0)
    saved_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    manual_action_count: int = Field(ge=0)
    remaining_count: int = Field(ge=0)
    future_eligible_count: int = Field(ge=0)
    detail_run_cap: int = Field(ge=0)


class RecoveryAttemptProjectionV1(FrozenContract):
    version: Literal[1] = 1
    request_event_sequence: int = Field(ge=1)
    requested_at: datetime
    requested_by: str | None = None
    strategy: Literal["fresh_profile", "reuse_open_browser"] | None = None
    trigger_classification: str | None = None
    outcome: Literal[
        "pending",
        "completed",
        "failed",
        "cancelled",
        "manual_action_required",
    ]
    outcome_event_sequence: int | None = Field(default=None, ge=1)
    outcome_at: datetime | None = None
    outcome_classification: str | None = None
    outcome_error: str | None = None

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> RecoveryAttemptProjectionV1:
        outcome_fields = (
            self.outcome_event_sequence,
            self.outcome_at,
        )
        if self.outcome == "pending":
            if any(value is not None for value in outcome_fields):
                raise ValueError("Pending recovery cannot claim an outcome event")
        elif any(value is None for value in outcome_fields):
            raise ValueError("Settled recovery requires an outcome event")
        return self


class CrawlControlRunProjectionV1(FrozenContract):
    version: Literal[1] = 1
    crawl_job_id: UUID
    source_site: SourceSite
    crawl_phase: Literal["listing", "detail"]
    crawl_mode: Literal["headless", "headed"]
    trigger_kind: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=64)
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    authority: RunAuthorityProjectionV1
    listing_workload: ListingWorkloadProjectionV1 | None = None
    detail_snapshot: DetailSnapshotProjectionV1 | None = None
    recovery_attempt: RecoveryAttemptProjectionV1 | None = None

    @model_validator(mode="after")
    def validate_phase_projection(self) -> CrawlControlRunProjectionV1:
        if self.crawl_phase == "listing":
            if self.listing_workload is None or self.detail_snapshot is not None:
                raise ValueError("Listing runs require only listing workload")
        elif self.detail_snapshot is None or self.listing_workload is not None:
            raise ValueError("Detail runs require only a detail snapshot")
        return self


class AutomationRowProjectionV1(FrozenContract):
    version: Literal[1] = 1
    automation_id: UUID
    revision: int = Field(ge=1)
    lifecycle_state: AutomationLifecycleState
    name: str = Field(min_length=1, max_length=255)
    source_site: SourceSite
    crawl_phase: Literal["listing", "detail"]
    crawl_mode: Literal["headless", "headed"]
    authored_scope: AuthoredCrawlScopeV1
    scope_review_reason: CrawlScopeErrorPayloadV1 | None = None
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

    @classmethod
    def from_projection(
        cls,
        projection: AutomationProjectionV1,
    ) -> AutomationRowProjectionV1:
        snapshot = projection.snapshot
        configuration = snapshot.configuration
        return cls(
            automation_id=snapshot.automation_id,
            revision=snapshot.revision,
            lifecycle_state=snapshot.lifecycle_state,
            name=configuration.name,
            source_site=configuration.scope.source_site,
            crawl_phase=configuration.crawl_phase,
            crawl_mode=configuration.crawl_mode,
            authored_scope=configuration.scope,
            scope_review_reason=snapshot.scope_review_reason,
            created_at=projection.created_at,
            updated_at=projection.updated_at,
            last_run_at=projection.last_run_at,
            next_run_at=projection.next_run_at,
        )


class TaskControlBoardProjectionV1(FrozenContract):
    version: Literal[1] = 1
    source_site: SourceSite | None = None
    automations: tuple[AutomationRowProjectionV1, ...]
    automation_total: int = Field(ge=0)
    runs: tuple[CrawlControlRunProjectionV1, ...]
    run_total: int = Field(ge=0)
    refreshed_at: datetime
