from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.crawl_phases import resolve_crawl_phase
from app.crawl_modes import resolve_crawl_mode
from app.schemas.scraper_pacing import DetailPacingConfig
from app.crawl_control.task_control_board_contracts import (
    DetailSnapshotProjectionV1,
    ListingWorkloadProjectionV1,
    ListingRecoveryProjectionV1,
    RecoveryAttemptProjectionV1,
    RunAuthorityProjectionV1,
)


class CrawlJobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_site: str
    crawl_phase: str | None = None
    crawl_mode: str | None = None
    trigger_type: str
    schedule_id: UUID | None
    status: str
    request_payload: dict
    requested_by: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    metrics: dict | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def resolve_output_crawl_mode(self) -> "CrawlJobSchema":
        payload = self.request_payload if isinstance(self.request_payload, dict) else {}
        self.crawl_phase = resolve_crawl_phase(payload.get("crawl_phase"))
        self.crawl_mode = resolve_crawl_mode(self.source_site, payload.get("crawl_mode"))
        return self


class CrawlJobEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    crawl_job_id: UUID
    sequence_no: int
    event_type: str
    payload: dict
    emitted_by: str | None
    created_at: datetime


class CrawlJobEventsResponse(BaseModel):
    events: list[CrawlJobEventSchema]
    total: int


class CrawlTaskListItemSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    crawl_job_id: str
    persisted_status: str
    status: str
    source_site: str
    crawl_mode: str | None = None
    crawl_phase: str
    dispatch_plan_id: str | None = None
    dispatch_plan_fingerprint: str | None = None
    automation_id: str | None = None
    authored_scope: dict | None = None
    resolved_scope: dict | None = None
    readiness: dict | None = None
    authority: RunAuthorityProjectionV1
    listing_workload: ListingWorkloadProjectionV1 | None = None
    detail_snapshot: DetailSnapshotProjectionV1 | None = None
    recovery_attempt: RecoveryAttemptProjectionV1 | None = None
    updated_at: str | None = None
    error: str | None = None
    issue_class: str | None = None
    issue_code: str | None = None
    issue_stage: str | None = None
    latest_issue_text: str | None = None
    request_payload: dict | None = None
    detail_pacing: DetailPacingConfig | None = None
    listing_recovery: ListingRecoveryProjectionV1 | None = None
    listing_completed: bool = False
    listing_partial: bool = False
    listing_condition_count: int = 0
    listing_natural_condition_count: int = 0
    listing_capped_condition_count: int = 0
    listing_capped_classification_ids: list[str] = Field(default_factory=list)


class CrawlTaskListResponse(BaseModel):
    items: list[CrawlTaskListItemSchema]
    total: int
    page: int
    page_size: int
    status: str | None = None
    source_site: str | None = None
    crawl_mode: str | None = None
    time_range: str = "all"
    refreshed_at: str
