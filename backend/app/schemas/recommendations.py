from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.job import (
    EmploymentTypeSchema,
    JobIntelligenceDomainAvailabilitySchema,
)
from app.schemas.job_intelligence import CanonicalJobStateSchema


class JobRecommendationIntelligenceAvailabilitySchema(BaseModel):
    source_attributes: JobIntelligenceDomainAvailabilitySchema
    canonical_taxonomy: JobIntelligenceDomainAvailabilitySchema
    skills: JobIntelligenceDomainAvailabilitySchema


class JobRecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    title: str
    company_name: Optional[str] = None
    location: Optional[str] = None
    employment_types: list[EmploymentTypeSchema]
    posted_date: Optional[str] = None
    canonical_taxonomy: Optional[CanonicalJobStateSchema]
    job_intelligence_availability: JobRecommendationIntelligenceAvailabilitySchema
    semantic_score: float
    skill_overlap_score: float
    taxonomy_score: float
    freshness_score: float
    combined_score: float

    @model_validator(mode="after")
    def keep_governed_data_aligned_with_availability(self):
        availability = self.job_intelligence_availability
        if not availability.source_attributes.available and self.employment_types:
            raise ValueError(
                "Unavailable Source Job Attributes cannot expose Employment Types"
            )
        if not availability.canonical_taxonomy.available:
            if self.canonical_taxonomy is not None:
                raise ValueError(
                    "Unavailable Canonical Job Taxonomy cannot expose a state"
                )
        elif self.canonical_taxonomy is None:
            raise ValueError(
                "Available Canonical Job Taxonomy requires an assigned or unassigned state"
            )
        return self


class JobRecommendationsResponse(BaseModel):
    source_job_id: UUID
    recommendations: list[JobRecommendationSchema]


JobRecommendationSchema.model_rebuild()
JobRecommendationsResponse.model_rebuild()
