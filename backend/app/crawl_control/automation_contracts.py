from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeErrorPayloadV1,
    DetailSettingsV1,
    FrozenContract,
    ListingSettingsV1,
    contract_fingerprint,
)


AutomationLifecycleState: TypeAlias = Literal[
    "active",
    "paused",
    "archived",
    "scope_review_required",
]


class AutomationConfigurationV1(FrozenContract):
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    cron_expression: str = Field(min_length=9, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)
    scope: AuthoredCrawlScopeV1
    listing_settings: ListingSettingsV1 | None = None
    detail_settings: DetailSettingsV1 | None = None

    @field_validator("name", "timezone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Automation text fields cannot be empty")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Invalid timezone identifier: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_execution_settings(self) -> AutomationConfigurationV1:
        if (self.listing_settings is None) == (self.detail_settings is None):
            raise ValueError(
                "Automation requires exactly one Listing or Detail settings contract"
            )
        if self.detail_settings is not None:
            if self.detail_settings.backlog_snapshot is not None:
                raise ValueError(
                    "Automation configuration cannot persist a run backlog snapshot"
                )
            backlog_scope = self.detail_settings.backlog_scope
            if backlog_scope.kind == "crawl_scope":
                if backlog_scope.scope != self.scope:
                    raise ValueError(
                        "Detail crawl_scope must reuse the Automation Authored Scope"
                    )
            elif self.scope.mode != "all":
                raise ValueError(
                    "Source backlog and Listing Batch detail Automations require "
                    "explicit all-source context"
                )
        return self

    @property
    def crawl_phase(self) -> Literal["listing", "detail"]:
        return "listing" if self.listing_settings is not None else "detail"

    @property
    def crawl_mode(self) -> Literal["headless", "headed"]:
        settings = self.listing_settings or self.detail_settings
        assert settings is not None
        return settings.crawl_mode


class AutomationSnapshotV1(FrozenContract):
    version: Literal[1] = 1
    automation_id: UUID
    revision: int = Field(ge=1)
    lifecycle_state: AutomationLifecycleState
    configuration: AutomationConfigurationV1
    scope_review_reason: CrawlScopeErrorPayloadV1 | None = None
    archived_at: datetime | None = None

    @field_validator("archived_at")
    @classmethod
    def require_aware_archived_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Automation archived_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_lifecycle_shape(self) -> AutomationSnapshotV1:
        if (self.lifecycle_state == "archived") != (self.archived_at is not None):
            raise ValueError("Archived Automation state and timestamp must agree")
        if (
            self.lifecycle_state == "scope_review_required"
            and self.scope_review_reason is None
        ):
            raise ValueError("scope_review_required requires a structured reason")
        return self

    @property
    def fingerprint(self) -> str:
        return contract_fingerprint(self)


class AutomationProjectionV1(FrozenContract):
    version: Literal[1] = 1
    snapshot: AutomationSnapshotV1
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

    @field_validator("created_at", "updated_at", "last_run_at", "next_run_at")
    @classmethod
    def require_aware_instant(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Automation instants must be timezone-aware UTC values")
        return value


class AutomationDeleteImpactV1(FrozenContract):
    version: Literal[1] = 1
    automation_id: UUID
    expected_revision: int = Field(ge=1)
    automation_revision_count: int = Field(ge=1)
    schedule_execution_count: int = Field(ge=0)
    crawl_job_count: int = Field(ge=0)
    removed_records: tuple[Literal["automation", "automation_revisions"], ...]
    preserved_records: tuple[
        Literal["schedule_executions", "crawl_jobs", "run_history"], ...
    ]

    @property
    def fingerprint(self) -> str:
        return contract_fingerprint(self)


class AutomationDeleteReviewGrantV1(FrozenContract):
    version: Literal[1] = 1
    review_token: str = Field(min_length=20)
    expires_at: datetime
    impact: AutomationDeleteImpactV1

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Automation delete review expiry must be timezone-aware")
        return value
