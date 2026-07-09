from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.crawl_phases import normalize_crawl_phase, normalize_detail_statuses, resolve_crawl_phase
from app.crawl_modes import normalize_crawl_mode, resolve_crawl_mode
from app.services.crawl_request_validation import (
    CategoryId,
    normalize_source_site,
    validate_crawl_request,
)


class CrawlJobCreateRequest(BaseModel):
    schedule_id: UUID | None = None
    source_site: str | None = Field(default=None, max_length=32)
    crawl_phase: str | None = Field(default=None, max_length=32)
    crawl_mode: str | None = Field(default=None, max_length=32)
    category_ids: list[CategoryId] | None = None
    keywords: str | None = Field(default=None, max_length=500)
    max_pages: int | None = Field(default=None, ge=1, le=1000)
    source_listing_crawl_job_id: UUID | None = None
    detail_limit: int = Field(default=100, ge=1, le=5000)
    detail_statuses: list[str] | None = None
    skip_existing: bool = Field(default=False)
    requested_by: str | None = Field(default=None, max_length=255)

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, value):
        if value is None:
            return None
        return normalize_source_site(value)

    @field_validator("crawl_mode", mode="before")
    @classmethod
    def normalize_crawl_mode_field(cls, value):
        return normalize_crawl_mode(value)

    @field_validator("crawl_phase", mode="before")
    @classmethod
    def normalize_crawl_phase_field(cls, value):
        return normalize_crawl_phase(value)

    @field_validator("detail_statuses", mode="before")
    @classmethod
    def normalize_detail_statuses_field(cls, value):
        return normalize_detail_statuses(value)

    @model_validator(mode="after")
    def validate_request_shape(self) -> "CrawlJobCreateRequest":
        if self.schedule_id is not None:
            return self

        validated = validate_crawl_request(
            source_site=self.source_site,
            crawl_phase=self.crawl_phase,
            crawl_mode=self.crawl_mode,
            category_ids=self.category_ids,
            source_listing_crawl_job_id=self.source_listing_crawl_job_id,
        )
        self.source_site = validated.source_site
        self.crawl_phase = validated.crawl_phase
        self.crawl_mode = validated.crawl_mode
        self.category_ids = validated.category_ids
        return self


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
    updated_at: str | None = None
    error: str | None = None
    issue_class: str | None = None
    issue_code: str | None = None
    issue_stage: str | None = None
    latest_issue_text: str | None = None
    request_payload: dict | None = None


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
