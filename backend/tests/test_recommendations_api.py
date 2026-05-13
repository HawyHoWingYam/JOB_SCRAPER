import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import recommendations as recommendations_api
from app.database import get_db


RECOMMENDATIONS_RESPONSE = {
    "source_job_id": str(uuid4()),
    "recommendations": [
        {
            "id": str(uuid4()),
            "job_id": "candidate-1",
            "title": "Platform Backend Engineer",
            "company_name": "Atlas Systems",
            "location": "Hong Kong",
            "employment_type": "Full-time",
            "posted_date": "2026-05-01T00:00:00+00:00",
            "job_taxonomy": {
                "domain_id": str(uuid4()),
                "domain_name": "Information & Communication Technology",
                "category_id": str(uuid4()),
                "category_name": "Software Development",
                "subcategory_id": str(uuid4()),
                "subcategory_name": "Backend Development",
                "path": "ICT / Software Development / Backend Development",
            },
            "semantic_score": 0.98,
            "skill_overlap_score": 1.0,
            "taxonomy_score": 1.0,
            "freshness_score": 1.0,
            "combined_score": 0.987,
        }
    ],
}


def _build_test_client():
    app = FastAPI()
    app.include_router(recommendations_api.router, prefix="/api/v1")

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_similar_jobs_endpoint_proxies_to_recommendation_api(monkeypatch):
    client = _build_test_client()
    captured = {}

    class FailingRecommendationService:
        def __init__(self, db):
            raise AssertionError("public recommendations should not instantiate local JobRecommendationService")

    class FakeRecommendationClient:
        def __init__(self, *, base_url=None, **kwargs):
            captured["base_url"] = base_url

        async def get_job_recommendations(self, job_id, *, limit=5):
            captured["job_id"] = job_id
            captured["limit"] = limit
            return RECOMMENDATIONS_RESPONSE

    monkeypatch.setattr(recommendations_api, "JobRecommendationService", FailingRecommendationService)
    monkeypatch.setattr(recommendations_api, "RecommendationClient", FakeRecommendationClient, raising=False)
    monkeypatch.setattr(recommendations_api.settings, "recommendation_api_url", "http://recommendation-api:8000")

    try:
        response = await client.get(f"/api/v1/jobs/{RECOMMENDATIONS_RESPONSE['source_job_id']}/similar?limit=3")
    finally:
        await client.aclose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_job_id"] == RECOMMENDATIONS_RESPONSE["source_job_id"]
    assert payload["recommendations"][0]["job_id"] == "candidate-1"
    assert captured["base_url"] == "http://recommendation-api:8000"
    assert captured["limit"] == 3


@pytest.mark.asyncio
async def test_recommendations_endpoint_returns_503_for_unconfigured_proxy(monkeypatch):
    client = _build_test_client()

    class FailingRecommendationService:
        def __init__(self, db):
            raise AssertionError("public recommendations should not instantiate local JobRecommendationService")

    monkeypatch.setattr(recommendations_api, "JobRecommendationService", FailingRecommendationService)
    monkeypatch.setattr(recommendations_api.settings, "recommendation_api_url", None)

    try:
        response = await client.get(f"/api/v1/recommendations/jobs?job_id={uuid4()}")
    finally:
        await client.aclose()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "recommendation_api_unavailable"
