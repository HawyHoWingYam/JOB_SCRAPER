import sys
import importlib.util
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import get_db


def _load_recommendations_api_module():
    module_path = BACKEND_ROOT / "app" / "api" / "recommendations.py"
    spec = importlib.util.spec_from_file_location("recommendations_api_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    recommendations_api = _load_recommendations_api_module()
    app = FastAPI()
    app.include_router(recommendations_api.router, prefix="/api/v1")

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver"), recommendations_api


@pytest.mark.asyncio
async def test_similar_jobs_endpoint_uses_recommendation_service(monkeypatch):
    client, recommendations_api = _build_test_client()
    captured = {}

    class FakeRecommendationService:
        def __init__(self, db):
            captured["db"] = db

        def recommend_for_job(self, job_id, *, limit=5):
            captured["job_id"] = job_id
            captured["limit"] = limit
            return RECOMMENDATIONS_RESPONSE["recommendations"]

    monkeypatch.setattr(recommendations_api, "JobRecommendationService", FakeRecommendationService)

    try:
        response = await client.get(f"/api/v1/jobs/{RECOMMENDATIONS_RESPONSE['source_job_id']}/similar?limit=3")
    finally:
        await client.aclose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_job_id"] == RECOMMENDATIONS_RESPONSE["source_job_id"]
    assert payload["recommendations"][0]["job_id"] == "candidate-1"
    assert captured["limit"] == 3


@pytest.mark.asyncio
async def test_recommendations_endpoint_returns_404_for_unknown_source_job(monkeypatch):
    client, recommendations_api = _build_test_client()

    class FakeRecommendationService:
        def __init__(self, db):
            self.db = db

        def recommend_for_job(self, job_id, *, limit=5):
            raise ValueError(f"Job not found: {job_id}")

    monkeypatch.setattr(recommendations_api, "JobRecommendationService", FakeRecommendationService)

    try:
        response = await client.get(f"/api/v1/recommendations/jobs?job_id={uuid4()}")
    finally:
        await client.aclose()

    assert response.status_code == 404
    assert response.json()["detail"].startswith("Job not found:")
