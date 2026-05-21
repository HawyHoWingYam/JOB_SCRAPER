from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.crawl_phases import normalize_crawl_phase, normalize_detail_statuses, resolve_crawl_phase
from app.crawl_modes import normalize_crawl_mode, resolve_crawl_mode
from app.schemas.schedule import CategoryId, normalize_source_site, validate_category_ids_for_source_site


class CrawlJobCreateRequest(BaseModel):
    schedule_id: UUID | None = None
    source_site: str | None = Field(default=None, max_length=32)
    crawl_phase: str | None = Field(default=None, max_length=32)
    crawl_mode: str | None = Field(default=None, max_length=32)
    category_ids: list[CategoryId] | None = None
    max_pages: int = Field(default=3, ge=1, le=1000)
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

        self.source_site = normalize_source_site(self.source_site)
        self.crawl_phase = resolve_crawl_phase(self.crawl_phase)
        self.crawl_mode = resolve_crawl_mode(self.source_site, self.crawl_mode)
        if self.crawl_phase == "listing":
            if not self.category_ids:
                raise ValueError("category_ids must be provided for listing crawl jobs")
            validate_category_ids_for_source_site(self.source_site, self.category_ids)
            return self

        if self.source_listing_crawl_job_id is None and not self.category_ids:
            raise ValueError("detail crawl jobs require source_listing_crawl_job_id or category_ids")
        if self.category_ids:
            validate_category_ids_for_source_site(self.source_site, self.category_ids)
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
