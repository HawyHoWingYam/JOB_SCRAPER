from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.job import JobTaxonomySchema


class JobRecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    title: str
    company_name: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    posted_date: Optional[str] = None
    job_taxonomy: Optional[JobTaxonomySchema] = None
    semantic_score: float
    skill_overlap_score: float
    taxonomy_score: float
    freshness_score: float
    combined_score: float


class JobRecommendationsResponse(BaseModel):
    source_job_id: UUID
    recommendations: list[JobRecommendationSchema]


JobRecommendationSchema.model_rebuild()
JobRecommendationsResponse.model_rebuild()
