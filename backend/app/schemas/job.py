from pydantic import BaseModel, ConfigDict, Field, field_serializer
from typing import Optional
from datetime import datetime
from uuid import UUID


class JobCreateSchema(BaseModel):
    """Schema for creating a new job."""

    job_id: str
    company_id: UUID
    title: str
    description: Optional[str] = None
    subcategory_id: Optional[UUID] = None
    source_classification_id: Optional[str] = None
    source_classification_name: Optional[str] = None
    source_subclassification_id: Optional[str] = None
    source_subclassification_name: Optional[str] = None
    ai_category: Optional[str] = None
    ai_summary: Optional[str] = None
    salary_range: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    posted_date: Optional[datetime] = None


class JobSchema(JobCreateSchema):
    """Schema for job response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class JobDetailSchema(JobSchema):
    """Expanded schema for the job detail view."""

    company_name: Optional[str] = None
    company_industry: Optional[str] = None
    company_ai_description: Optional[str] = None
    ai_enriched_at: Optional[datetime] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    experience_level: Optional[str] = None
    experience_summary: Optional[str] = None
    experience_evidence: Optional[list[str]] = None
    expiry_date: Optional[str] = None
    is_expired: Optional[bool] = None
    skills: list[str] = Field(default_factory=list)
    generic_tags: list[str] = Field(default_factory=list)

    @field_serializer("ai_enriched_at")
    def serialize_ai_enriched_at(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value is not None else None
