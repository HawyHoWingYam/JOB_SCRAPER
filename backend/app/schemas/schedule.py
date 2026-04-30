from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from typing import Optional, List
from datetime import datetime
from uuid import UUID


CategoryId = StrictInt | StrictStr


def normalize_source_site(source_site: Optional[str]) -> str:
    """Normalize schedule source site values to the persisted default."""
    return (source_site or "").strip().lower() or "jobsdb"


def validate_category_ids_for_source_site(
    source_site: Optional[str],
    category_ids: Optional[List[CategoryId]],
) -> None:
    """Enforce source-specific category id types."""
    normalized_source_site = normalize_source_site(source_site)

    if normalized_source_site == "ctgoodjobs" and not category_ids:
        raise ValueError("CTgoodjobs category_ids must be provided and non-empty")

    if category_ids is None:
        return

    if normalized_source_site == "jobsdb":
        if any(not isinstance(category_id, int) for category_id in category_ids):
            raise ValueError("JobsDB category_ids must be integers")
        return

    if normalized_source_site == "ctgoodjobs":
        invalid_category_ids = [
            category_id
            for category_id in category_ids
            if not isinstance(category_id, str) or not category_id.startswith("ctgoodjobs:")
        ]
        if invalid_category_ids:
            raise ValueError("CTgoodjobs category_ids must be strings like 'ctgoodjobs:021'")


# ============== Schedule Schemas ==============

class ScheduleCreateSchema(BaseModel):
    """Schema for creating a new schedule."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    cron_expression: str = Field(..., min_length=9, max_length=100)
    timezone: str = Field(default="Asia/Hong_Kong")
    source_site: str = Field(default="jobsdb", max_length=32)
    category_ids: Optional[List[CategoryId]] = None
    keywords: Optional[str] = None
    location: str = Field(default="Hong Kong")
    max_pages: int = Field(default=3, ge=1, le=1000)
    is_active: bool = Field(default=True)

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        return normalize_source_site(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ScheduleCreateSchema":
        validate_category_ids_for_source_site(self.source_site, self.category_ids)
        return self


class ScheduleUpdateSchema(BaseModel):
    """Schema for updating a schedule."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    cron_expression: Optional[str] = Field(None, min_length=9, max_length=100)
    timezone: Optional[str] = None
    source_site: Optional[str] = Field(default=None, max_length=32)
    category_ids: Optional[List[CategoryId]] = None
    keywords: Optional[str] = None
    location: Optional[str] = None
    max_pages: Optional[int] = Field(None, ge=1, le=1000)
    is_active: Optional[bool] = None

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        if v is None:
            return None
        return normalize_source_site(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ScheduleUpdateSchema":
        if self.category_ids is not None and self.source_site is not None:
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
    category_ids: Optional[List[CategoryId]]
    keywords: Optional[str]
    location: str
    max_pages: int
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

# ============== Execution Schemas ==============

class ExecutionSchema(BaseModel):
    """Schema for execution history response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schedule_id: UUID
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
    category_ids: List[CategoryId] = Field(..., min_length=1)
    max_pages: int = Field(default=3, ge=1, le=1000)
    skip_existing: bool = Field(default=False, description="If True, skip jobs that already exist. If False, update existing jobs.")

    @field_validator("source_site", mode="before")
    @classmethod
    def normalize_source_site_field(cls, v):
        return normalize_source_site(v)

    @model_validator(mode="after")
    def validate_category_ids(self) -> "ImmediateScrapeRequest":
        validate_category_ids_for_source_site(self.source_site, self.category_ids)
        return self
