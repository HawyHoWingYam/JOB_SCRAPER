from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.crawl_control.automation_contracts import (
    AutomationConfigurationV1,
    AutomationProjectionV1,
)
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeErrorPayloadV1,
    DetailBacklogScopeV1,
    FrozenContract,
    ListingWorkloadPreviewV1,
    ResolvedRunScopeV1,
    SHA256_PATTERN,
)
from app.crawl_control.dispatch_plan_contracts import DispatchPlanReadinessV1


class AutomationReviewRequestV1(FrozenContract):
    configuration: AutomationConfigurationV1
    automation_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_edit_binding(self) -> AutomationReviewRequestV1:
        if (self.automation_id is None) != (self.expected_revision is None):
            raise ValueError(
                "Automation review edit ID and expected revision must be supplied together"
            )
        return self


class AutomationDetailPreviewV1(FrozenContract):
    backlog_scope: DetailBacklogScopeV1
    eligible_now_count: int = Field(ge=0)
    selected_now_count: int = Field(ge=0)
    limit_kind: Literal["entire_snapshot", "stop_after"]
    detail_run_cap: int = Field(ge=1)
    absolute_safety_cap: int = Field(ge=1)
    snapshot_frozen: Literal[False] = False

    @model_validator(mode="after")
    def validate_counts(self) -> AutomationDetailPreviewV1:
        if self.selected_now_count > self.eligible_now_count:
            raise ValueError("Detail preview cannot select more than is eligible")
        return self


class AutomationScheduleSummaryV1(FrozenContract):
    cron_expression: str = Field(min_length=9, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)
    human_summary: str = Field(min_length=1, max_length=500)
    next_run_at: datetime

    @field_validator("next_run_at")
    @classmethod
    def require_aware_next_run(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Automation review next run must be timezone-aware")
        return value


class AutomationReviewV1(FrozenContract):
    version: Literal[1] = 1
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    automation_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    catalog_revision_id: UUID
    authored_scope: AuthoredCrawlScopeV1
    resolved_scope: ResolvedRunScopeV1
    listing_workload: ListingWorkloadPreviewV1 | None = None
    detail_preview: AutomationDetailPreviewV1 | None = None
    schedule_summary: AutomationScheduleSummaryV1
    readiness: DispatchPlanReadinessV1
    warnings: tuple[CrawlScopeErrorPayloadV1, ...] = Field(default_factory=tuple)
    before: AutomationProjectionV1 | None = None

    @model_validator(mode="after")
    def validate_phase_projection(self) -> AutomationReviewV1:
        if (self.listing_workload is None) == (self.detail_preview is None):
            raise ValueError(
                "Automation review requires exactly one listing or detail preview"
            )
        if self.resolved_scope.authored_scope != self.authored_scope:
            raise ValueError("Automation review scope projections differ")
        if self.resolved_scope.catalog_revision_id != self.catalog_revision_id:
            raise ValueError("Automation review catalog revisions differ")
        return self
