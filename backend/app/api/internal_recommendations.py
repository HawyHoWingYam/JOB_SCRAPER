from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recommendations import JobRecommendationSchema, JobRecommendationsResponse
from app.services.jev_related_jobs import JevRelatedJobsService

router = APIRouter(prefix="/internal", tags=["recommendations"])


def _build_recommendations_response(
    *,
    source_job_id: UUID,
    limit: int,
    db: Session,
) -> JobRecommendationsResponse:
    service = JevRelatedJobsService(db)
    try:
        read_state = service.read(source_job_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return JobRecommendationsResponse(
        source_job_id=source_job_id,
        jev_status=str(read_state["jev_status"]),
        jev_evaluation_id=read_state["jev_evaluation_id"],
        recommendations=[
            JobRecommendationSchema.model_validate(item)
            for item in read_state["recommendations"]
        ],
    )


@router.get("/jobs/{job_id}/similar", response_model=JobRecommendationsResponse)
async def get_similar_jobs_internal(
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
async def get_job_recommendations_internal(
    job_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return _build_recommendations_response(
        source_job_id=job_id,
        limit=limit,
        db=db,
    )
