from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from typing import Optional, List
from app.crawl_phases import normalize_crawl_phase, resolve_crawl_phase
from app.crawl_modes import normalize_crawl_mode, resolve_crawl_mode
from app.services.crawl_request_validation import (
    CategoryId,
    normalize_source_site,
    validate_category_ids_for_source_site,
    validate_crawl_request,
)
from datetime import datetime
from uuid import UUID


# ============== Schedule Schemas ==============

class ScheduleCreateSchema(BaseModel):
    """Schema for creating a new schedule."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    cron_expression: str = Field(..., min_length=9, max_length=100)
    timezone: str = Field(default="Asia/Hong_Kong")
    source_site: str = Field(default="jobsdb", max_length=32)
    crawl_phase: Optional[str] = Field(default=None, max_length=32)
    crawl_mode: Optional[str] = Field(default=None, max_length=32)
    category_ids: Optional[List[CategoryId]] = None
    keywords: Optional[str] = None
    location: str = Field(default="Hong Kong")
    max_pages: int = Field(default=3, ge=1, le=1000)
    detail_limit: int = Field(default=100, ge=1, le=5000)
    is_active: bool = Field(default=True)

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        return normalize_source_site(v)

    @field_validator("crawl_mode", mode="before")
    @classmethod
    def normalize_crawl_mode_field(cls, v):
        return normalize_crawl_mode(v)

    @field_validator("crawl_phase", mode="before")
    @classmethod
    def normalize_crawl_phase_field(cls, v):
        return normalize_crawl_phase(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ScheduleCreateSchema":
        validated = validate_crawl_request(
            source_site=self.source_site,
            crawl_phase=self.crawl_phase,
            crawl_mode=self.crawl_mode,
            category_ids=self.category_ids,
            source_listing_crawl_job_id=None,
        )
        self.source_site = validated.source_site
        self.crawl_phase = validated.crawl_phase
        self.crawl_mode = validated.crawl_mode
        self.category_ids = validated.category_ids
        return self


class ScheduleUpdateSchema(BaseModel):
    """Schema for updating a schedule."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    cron_expression: Optional[str] = Field(None, min_length=9, max_length=100)
    timezone: Optional[str] = None
    source_site: Optional[str] = Field(default=None, max_length=32)
    crawl_phase: Optional[str] = Field(default=None, max_length=32)
    crawl_mode: Optional[str] = Field(default=None, max_length=32)
    category_ids: Optional[List[CategoryId]] = None
    keywords: Optional[str] = None
    location: Optional[str] = None
    max_pages: Optional[int] = Field(None, ge=1, le=1000)
    detail_limit: Optional[int] = Field(None, ge=1, le=5000)
    is_active: Optional[bool] = None

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        if v is None:
            return None
        return normalize_source_site(v)

    @field_validator("crawl_mode", mode="before")
    @classmethod
    def normalize_crawl_mode_field(cls, v):
        return normalize_crawl_mode(v)

    @field_validator("crawl_phase", mode="before")
    @classmethod
    def normalize_crawl_phase_field(cls, v):
        return normalize_crawl_phase(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ScheduleUpdateSchema":
        if self.category_ids is not None and self.source_site is not None:
            if self.category_ids:
                validate_crawl_request(
                    source_site=self.source_site,
                    crawl_phase=self.crawl_phase,
                    crawl_mode=self.crawl_mode,
                    category_ids=self.category_ids,
                    source_listing_crawl_job_id=None,
                )
            else:
                validate_category_ids_for_source_site(self.source_site, self.category_ids)
        return self


class ScheduleSchema(BaseModel):
    """Schema for schedule response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    cron_expression: str
    timezone: str
    source_site: str
    crawl_phase: Optional[str]
    crawl_mode: Optional[str]
    category_ids: Optional[List[CategoryId]]
    keywords: Optional[str]
    location: str
    max_pages: int
    detail_limit: int
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def resolve_output_crawl_mode(self) -> "ScheduleSchema":
        self.crawl_phase = resolve_crawl_phase(self.crawl_phase)
        self.crawl_mode = resolve_crawl_mode(self.source_site, self.crawl_mode)
        return self

# ============== Execution Schemas ==============

class ExecutionSchema(BaseModel):
    """Schema for execution history response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schedule_id: UUID
    crawl_job_id: Optional[UUID]
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    jobs_scraped: int
    jobs_saved: int
    phase1_completed: bool
    phase2_completed: bool
    phase3_completed: bool
    phase4_completed: bool
    phase5_completed: bool
    ids_collected: int
    jobs_classified: int
    error_message: Optional[str]
    created_at: datetime

class ScheduleWithExecutionsSchema(ScheduleSchema):
    """Schedule with recent executions."""

    executions: List[ExecutionSchema] = []


# ============== Request/Response Schemas ==============

class ScheduleListResponse(BaseModel):
    """Response for listing schedules."""

    schedules: List[ScheduleSchema]
    total: int


class ExecutionListResponse(BaseModel):
    """Response for listing executions."""

    executions: List[ExecutionSchema]
    total: int


class ScheduleToggleResponse(BaseModel):
    """Response for toggling schedule status."""

    id: UUID
    is_active: bool
    next_run_at: Optional[datetime]


class ImmediateScrapeRequest(BaseModel):
    """Request for immediate scraping without schedule."""

    source_site: str = Field(default="jobsdb", max_length=32)
    crawl_phase: Optional[str] = Field(default=None, max_length=32)
    crawl_mode: Optional[str] = Field(default=None, max_length=32)
    category_ids: Optional[List[CategoryId]] = None
    max_pages: int = Field(default=3, ge=1, le=1000)
    source_listing_crawl_job_id: UUID | None = None
    detail_limit: int = Field(default=100, ge=1, le=5000)
    skip_existing: bool = Field(default=False, description="If True, skip jobs that already exist. If False, update existing jobs.")

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        return normalize_source_site(v)

    @field_validator("crawl_mode", mode="before")
    @classmethod
    def normalize_crawl_mode_field(cls, v):
        return normalize_crawl_mode(v)

    @field_validator("crawl_phase", mode="before")
    @classmethod
    def normalize_crawl_phase_field(cls, v):
        return normalize_crawl_phase(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ImmediateScrapeRequest":
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
