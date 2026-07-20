from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeErrorPayloadV1,
    DetailSettingsV1,
    FrozenContract,
    JsonScalar,
    ListingSettingsV1,
    ResolvedRunScopeV1,
    SHA256_PATTERN,
)
from app.source_catalog.domain import payload_fingerprint


DispatchPlanState: TypeAlias = Literal["prepared", "consumed", "expired"]
DispatchTriggerKind: TypeAlias = Literal[
    "one_off",
    "saved_automation",
    "scheduled_automation",
]


class DispatchPlanReadinessV1(FrozenContract):
    version: Literal[1] = 1
    status: Literal["ready", "blocked"]
    checked_at: datetime
    blocking_errors: tuple[CrawlScopeErrorPayloadV1, ...] = Field(
        default_factory=tuple
    )
    capabilities: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("checked_at")
    @classmethod
    def require_aware_checked_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dispatch Plan readiness timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_readiness_shape(self) -> DispatchPlanReadinessV1:
        if (self.status == "ready") == bool(self.blocking_errors):
            raise ValueError(
                "Ready Dispatch Plans cannot contain blocking errors and blocked "
                "plans require one"
            )
        return self


class DispatchPlanContentV1(FrozenContract):
    version: Literal[1] = 1
    source_site: Literal["jobsdb", "ctgoodjobs", "offertoday"]
    crawl_phase: Literal["listing", "detail"]
    trigger_kind: DispatchTriggerKind
    automation_id: UUID | None = None
    expected_automation_revision: int | None = Field(default=None, ge=1)
    catalog_revision_id: UUID
    authored_scope: AuthoredCrawlScopeV1
    resolved_scope: ResolvedRunScopeV1
    listing_settings: ListingSettingsV1 | None = None
    detail_settings: DetailSettingsV1 | None = None

    @model_validator(mode="after")
    def validate_content_shape(self) -> DispatchPlanContentV1:
        if self.trigger_kind == "one_off":
            if self.automation_id is not None or self.expected_automation_revision is not None:
                raise ValueError("One-off Dispatch Plans cannot bind an Automation")
        elif self.automation_id is None or self.expected_automation_revision is None:
            raise ValueError(
                "Automation Dispatch Plans require an Automation ID and revision"
            )

        if self.crawl_phase == "listing":
            if self.listing_settings is None or self.detail_settings is not None:
                raise ValueError(
                    "Listing Dispatch Plans require only Listing settings"
                )
        elif self.detail_settings is None or self.listing_settings is not None:
            raise ValueError("Detail Dispatch Plans require only Detail settings")

        if self.authored_scope.source_site != self.source_site:
            raise ValueError("Dispatch Plan and Authored Crawl Scope sources differ")
        if self.resolved_scope.source_site != self.source_site:
            raise ValueError("Dispatch Plan and Resolved Crawl Scope sources differ")
        if self.resolved_scope.authored_scope != self.authored_scope:
            raise ValueError("Dispatch Plan Authored and Resolved Crawl Scopes differ")
        if self.resolved_scope.catalog_revision_id != self.catalog_revision_id:
            raise ValueError("Dispatch Plan catalog revisions differ")

        if self.detail_settings is not None:
            backlog_scope = self.detail_settings.backlog_scope
            if backlog_scope.kind == "crawl_scope":
                if backlog_scope.scope != self.authored_scope:
                    raise ValueError(
                        "Detail crawl_scope must reuse the Dispatch Plan Authored Scope"
                    )
            elif self.authored_scope.mode != "all":
                raise ValueError(
                    "Source backlog and Listing Batch plans require all-source context"
                )
        return self


class DispatchPlanTargetRowV1(FrozenContract):
    version: Literal[1] = 1
    crawl_job_listing_id: UUID
    row_order: int = Field(ge=0)
    eligibility_fingerprint: str = Field(pattern=SHA256_PATTERN)
    eligibility_status: str = Field(min_length=1, max_length=32)
    status_metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class DispatchPlanTargetV1(FrozenContract):
    version: Literal[1] = 1
    source_site: Literal["jobsdb", "ctgoodjobs", "offertoday"]
    source_job_id: str = Field(min_length=1, max_length=255)
    selection_order: int = Field(ge=0)
    eligibility_fingerprint: str = Field(pattern=SHA256_PATTERN)
    eligibility_status: str = Field(min_length=1, max_length=32)
    status_metadata: dict[str, JsonScalar] = Field(default_factory=dict)
    rows: tuple[DispatchPlanTargetRowV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_row_membership(self) -> DispatchPlanTargetV1:
        row_orders = tuple(row.row_order for row in self.rows)
        if row_orders != tuple(range(len(self.rows))):
            raise ValueError("Dispatch Plan target row order must be contiguous")
        row_ids = {row.crawl_job_listing_id for row in self.rows}
        if len(row_ids) != len(self.rows):
            raise ValueError("Dispatch Plan target rows must be unique")
        return self


def dispatch_plan_fingerprint(
    *,
    plan_id: UUID,
    content: DispatchPlanContentV1,
    readiness: DispatchPlanReadinessV1,
    targets: tuple[DispatchPlanTargetV1, ...],
    confirmation_required: bool,
    prepared_by: str,
    prepared_at: datetime,
    expires_at: datetime,
) -> str:
    return payload_fingerprint(
        {
            "version": 1,
            "plan_id": str(plan_id),
            "content": content.model_dump(mode="json"),
            "readiness": readiness.model_dump(mode="json"),
            "targets": [target.model_dump(mode="json") for target in targets],
            "confirmation_required": confirmation_required,
            "prepared_by": prepared_by,
            "prepared_at": prepared_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )


class DispatchPlanSnapshotV1(FrozenContract):
    version: Literal[1] = 1
    plan_id: UUID
    state: DispatchPlanState
    content: DispatchPlanContentV1
    readiness: DispatchPlanReadinessV1
    targets: tuple[DispatchPlanTargetV1, ...] = Field(default_factory=tuple)
    detail_target_count: int = Field(ge=0)
    plan_fingerprint: str = Field(pattern=SHA256_PATTERN)
    confirmation_required: bool
    prepared_by: str = Field(min_length=1, max_length=255)
    prepared_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    crawl_job_id: UUID | None = None

    @field_validator("prepared_by")
    @classmethod
    def strip_prepared_by(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dispatch Plan preparer is required")
        return value

    @field_validator("prepared_at", "expires_at", "consumed_at")
    @classmethod
    def require_aware_instants(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Dispatch Plan timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_shape(self) -> DispatchPlanSnapshotV1:
        if self.expires_at <= self.prepared_at:
            raise ValueError("Dispatch Plan expiry must follow preparation")
        target_orders = tuple(target.selection_order for target in self.targets)
        if target_orders != tuple(range(len(self.targets))):
            raise ValueError("Dispatch Plan target order must be contiguous")
        target_identities = {
            (target.source_site, target.source_job_id) for target in self.targets
        }
        if len(target_identities) != len(self.targets):
            raise ValueError("Dispatch Plan targets must be unique")
        if any(target.source_site != self.content.source_site for target in self.targets):
            raise ValueError("Dispatch Plan target belongs to another source")
        if self.detail_target_count != len(self.targets):
            raise ValueError("Dispatch Plan detail target count is inconsistent")
        if self.content.crawl_phase == "listing" and self.targets:
            raise ValueError("Listing Dispatch Plans cannot contain detail targets")
        if (
            self.content.crawl_phase == "detail"
            and self.readiness.status == "ready"
            and not self.targets
        ):
            raise ValueError("Ready Detail Dispatch Plans require target membership")
        if self.state == "prepared":
            if self.consumed_at is not None or self.crawl_job_id is not None:
                raise ValueError("Prepared Dispatch Plan cannot have consumption data")
        elif self.state == "consumed":
            if self.consumed_at is None or self.crawl_job_id is None:
                raise ValueError("Consumed Dispatch Plan requires one Crawl Job")
        elif self.consumed_at is not None or self.crawl_job_id is not None:
            raise ValueError("Expired Dispatch Plan cannot have consumption data")

        expected_fingerprint = dispatch_plan_fingerprint(
            plan_id=self.plan_id,
            content=self.content,
            readiness=self.readiness,
            targets=self.targets,
            confirmation_required=self.confirmation_required,
            prepared_by=self.prepared_by,
            prepared_at=self.prepared_at,
            expires_at=self.expires_at,
        )
        if self.plan_fingerprint != expected_fingerprint:
            raise ValueError("Dispatch Plan fingerprint does not match its snapshot")
        return self


class DispatchPlanPreparationV1(FrozenContract):
    version: Literal[1] = 1
    plan: DispatchPlanSnapshotV1
    confirmation_token: str | None = Field(default=None, min_length=20)

    @model_validator(mode="after")
    def validate_confirmation_shape(self) -> DispatchPlanPreparationV1:
        should_return_token = (
            self.plan.readiness.status == "ready"
            and self.plan.confirmation_required
        )
        if should_return_token != (self.confirmation_token is not None):
            raise ValueError("Dispatch Plan confirmation token shape is inconsistent")
        return self


class ExecutionAuthorityV1(FrozenContract):
    version: Literal[1] = 1
    crawl_job_id: UUID
    dispatch_plan: DispatchPlanSnapshotV1

    @model_validator(mode="after")
    def validate_consumed_authority(self) -> ExecutionAuthorityV1:
        if self.dispatch_plan.state != "consumed":
            raise ValueError("Execution authority requires a consumed Dispatch Plan")
        if self.dispatch_plan.crawl_job_id != self.crawl_job_id:
            raise ValueError("Execution authority Crawl Job linkage is inconsistent")
        return self


class ExecutionResumeContextV1(FrozenContract):
    """Mutable retry controls that cannot redefine immutable plan authority."""

    version: Literal[1] = 1
    is_resume: Literal[True] = True
    manual_action_event_sequence: int = Field(ge=1)
    requested_at: datetime
    resume_strategy: Literal["fresh_profile", "reuse_open_browser"]
    manual_action_classification: str | None = Field(default=None, max_length=100)
    detail_statuses: tuple[
        Literal["pending", "failed", "manual_action_required"], ...
    ] = Field(default_factory=tuple)
    browser_channel: str | None = Field(default=None, max_length=100)
    browser_profile_path: str | None = Field(default=None, max_length=2048)

    @field_validator("requested_at")
    @classmethod
    def require_aware_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution resume timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_browser_overlay(self) -> ExecutionResumeContextV1:
        if self.resume_strategy == "reuse_open_browser":
            if not self.browser_channel or not self.browser_profile_path:
                raise ValueError(
                    "Reusable-browser resume requires channel and profile path"
                )
        elif self.browser_channel is not None or self.browser_profile_path is not None:
            raise ValueError(
                "Fresh-profile resume cannot carry reusable-browser settings"
            )
        return self


class DispatchPlanCleanupResultV1(FrozenContract):
    version: Literal[1] = 1
    expired_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def require_aware_completed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dispatch Plan cleanup timestamp must be timezone-aware")
        return value
