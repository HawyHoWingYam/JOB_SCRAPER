from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.job import (
    EmploymentTypeSchema,
    JobIntelligenceDomainAvailabilitySchema,
)


class JobRecommendationIntelligenceAvailabilitySchema(BaseModel):
    source_attributes: JobIntelligenceDomainAvailabilitySchema
    skills: JobIntelligenceDomainAvailabilitySchema


class JobRecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    title: str
    company_name: Optional[str] = None
    location: Optional[str] = None
    employment_types: list[EmploymentTypeSchema] = Field(default_factory=list)
    posted_date: Optional[str] = None
    job_intelligence_availability: Optional[
        JobRecommendationIntelligenceAvailabilitySchema
    ] = None
    semantic_score: Optional[float] = None
    skill_overlap_score: Optional[float] = None
    freshness_score: Optional[float] = None
    combined_score: Optional[float] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def keep_governed_data_aligned_with_availability(self):
        availability = self.job_intelligence_availability
        if (
            availability is not None
            and not availability.source_attributes.available
            and self.employment_types
        ):
            raise ValueError(
                "Unavailable Source Job Attributes cannot expose Employment Types"
            )
        return self


class JobRecommendationsResponse(BaseModel):
    source_job_id: UUID
    recommendations: list[JobRecommendationSchema]
    result_source: str = "similarity"


JobRecommendationSchema.model_rebuild()
JobRecommendationsResponse.model_rebuild()
