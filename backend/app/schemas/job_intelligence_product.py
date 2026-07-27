from __future__ import annotations

from pydantic import BaseModel

from app.schemas.company import CompanyProductSchema
from app.schemas.job import JobDetailSchema
from app.schemas.job_search import FilterOptionsResponse, JobSearchResponse
from app.schemas.recommendations import JobRecommendationsResponse


class JobIntelligenceProductFixtureSchema(BaseModel):
    job_filters: FilterOptionsResponse
    job_search: JobSearchResponse
    companies: list[CompanyProductSchema]
    job_detail: JobDetailSchema
    job_recommendations: JobRecommendationsResponse


__all__ = [
    "JobIntelligenceProductFixtureSchema",
]
