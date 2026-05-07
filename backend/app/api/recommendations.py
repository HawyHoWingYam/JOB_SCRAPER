from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.job import JobTaxonomySchema
from app.services.job_recommendation_service import JobRecommendationService

router = APIRouter(tags=["recommendations"])


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


def _build_recommendations_response(
    *,
    source_job_id: UUID,
    limit: int,
    db: Session,
) -> JobRecommendationsResponse:
    service = JobRecommendationService(db)
    try:
        recommendations = service.recommend_for_job(source_job_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobRecommendationsResponse(
        source_job_id=source_job_id,
        recommendations=[
            JobRecommendationSchema.model_validate(item)
            for item in recommendations
        ],
    )


@router.get("/jobs/{job_id}/similar", response_model=JobRecommendationsResponse)
async def get_similar_jobs(
    job_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return _build_recommendations_response(
        source_job_id=job_id,
        limit=limit,
        db=db,
    )


@router.get("/recommendations/jobs", response_model=JobRecommendationsResponse)
async def get_job_recommendations(
    job_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return _build_recommendations_response(
        source_job_id=job_id,
        limit=limit,
        db=db,
    )
