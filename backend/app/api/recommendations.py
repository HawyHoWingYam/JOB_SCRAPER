from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.schemas.recommendations import JobRecommendationsResponse
from app.services.recommendation_client import (
    RecommendationClient,
    RecommendationClientResponseError,
    RecommendationClientUnavailableError,
)

router = APIRouter(tags=["recommendations"])


async def _proxy_recommendations_response(
    *,
    source_job_id: UUID,
    limit: int,
) -> JobRecommendationsResponse:
    client = RecommendationClient(base_url=settings.recommendation_api_url)
    try:
        response_payload = await client.get_job_recommendations(source_job_id, limit=limit)
    except RecommendationClientResponseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except RecommendationClientUnavailableError:
        return JobRecommendationsResponse(
            source_job_id=source_job_id,
            recommendations=[],
        )

    return JobRecommendationsResponse.model_validate(response_payload)


@router.get("/jobs/{job_id}/similar", response_model=JobRecommendationsResponse)
async def get_similar_jobs(
    job_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
):
    return await _proxy_recommendations_response(
        source_job_id=job_id,
        limit=limit,
    )


@router.get("/recommendations/jobs", response_model=JobRecommendationsResponse)
async def get_job_recommendations(
    job_id: UUID,
    limit: int = Query(default=5, ge=1, le=20),
):
    return await _proxy_recommendations_response(
        source_job_id=job_id,
        limit=limit,
    )
