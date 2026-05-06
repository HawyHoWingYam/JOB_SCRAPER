from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.schedule import CategoryId, normalize_source_site, validate_category_ids_for_source_site


class CrawlJobCreateRequest(BaseModel):
    schedule_id: UUID | None = None
    source_site: str | None = Field(default=None, max_length=32)
    category_ids: list[CategoryId] | None = None
    max_pages: int = Field(default=3, ge=1, le=1000)
    skip_existing: bool = Field(default=False)
    requested_by: str | None = Field(default=None, max_length=255)

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, value):
        if value is None:
            return None
        return normalize_source_site(value)

    @model_validator(mode="after")
    def validate_request_shape(self) -> "CrawlJobCreateRequest":
        if self.schedule_id is not None:
            return self

        self.source_site = normalize_source_site(self.source_site)
        if not self.category_ids:
            raise ValueError("category_ids must be provided when schedule_id is omitted")

        validate_category_ids_for_source_site(self.source_site, self.category_ids)
        return self


class CrawlJobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_site: str
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
