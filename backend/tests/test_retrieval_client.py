import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import jobs as jobs_api
from app.database import get_db


SEARCH_RESPONSE = {
    "jobs": [],
    "total": 0,
    "page": 1,
    "page_size": 20,
    "total_pages": 0,
    "applied_scope": {
        "layers": [
            {
                "client_id": "root",
                "text_expression": "platform",
                "structured_filters": {},
            }
        ]
    },
    "layer_summaries": [
        {
            "client_id": "root",
            "label": "platform",
        }
    ],
}


def _build_test_client():
    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api/v1")

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_search_jobs_post_keeps_lexical_requests_local(monkeypatch):
    client = _build_test_client()
    captured = {}

    class FakeRetrievalService:
        def __init__(self, db):
            captured["db"] = db

        def search(self, request, *, layer_summaries=None):
            captured["request"] = request
            captured["layer_summaries"] = layer_summaries
            return SEARCH_RESPONSE

    class FailingRetrievalClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("lexical search should not instantiate RetrievalClient")

    monkeypatch.setattr(jobs_api, "RetrievalService", FakeRetrievalService)
    monkeypatch.setattr(jobs_api, "RetrievalClient", FailingRetrievalClient, raising=False)
    try:
        response = await client.post(
            "/api/v1/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "platform",
                            "structured_filters": {},
                        }
                    ]
                },
                "retrieval_mode": "lexical",
                "page": 1,
                "page_size": 20,
            },
        )
    finally:
        await client.aclose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["applied_scope"]["layers"][0]["client_id"] == "root"
    assert payload["applied_scope"]["layers"][0]["text_expression"] == "platform"
    assert captured["request"].retrieval_mode == "lexical"
    assert captured["layer_summaries"][0].client_id == "root"


@pytest.mark.asyncio
async def test_search_jobs_post_proxies_semantic_requests_to_retrieval_api(monkeypatch):
    client = _build_test_client()
    captured = {}

    class FailingRetrievalService:
        def __init__(self, db):
            raise AssertionError("semantic search should not instantiate local RetrievalService")

    class FakeRetrievalClient:
        def __init__(self, *, base_url=None, **kwargs):
            captured["base_url"] = base_url

        async def search_jobs(self, payload):
            captured["payload"] = payload
            return SEARCH_RESPONSE

    monkeypatch.setattr(jobs_api, "RetrievalService", FailingRetrievalService)
    monkeypatch.setattr(jobs_api, "RetrievalClient", FakeRetrievalClient, raising=False)
    monkeypatch.setattr(jobs_api.settings, "retrieval_api_url", "http://retrieval-api:8000")
    try:
        response = await client.post(
            "/api/v1/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "platform",
                            "structured_filters": {},
                        }
                    ]
                },
                "retrieval_mode": "semantic",
                "page": 1,
                "page_size": 20,
            },
        )
    finally:
        await client.aclose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["applied_scope"]["layers"][0]["client_id"] == "root"
    assert payload["applied_scope"]["layers"][0]["text_expression"] == "platform"
    assert captured["base_url"] == "http://retrieval-api:8000"
    assert captured["payload"]["retrieval_mode"] == "semantic"
    assert captured["payload"]["layer_summaries"][0]["client_id"] == "root"


@pytest.mark.asyncio
async def test_search_jobs_post_returns_503_when_semantic_proxy_is_unconfigured(monkeypatch):
    client = _build_test_client()

    class FailingRetrievalService:
        def __init__(self, db):
            raise AssertionError("semantic search should not instantiate local RetrievalService")

    monkeypatch.setattr(jobs_api, "RetrievalService", FailingRetrievalService)
    monkeypatch.setattr(jobs_api.settings, "retrieval_api_url", None)
    try:
        response = await client.post(
            "/api/v1/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "platform",
                            "structured_filters": {},
                        }
                    ]
                },
                "retrieval_mode": "hybrid",
                "page": 1,
                "page_size": 20,
            },
        )
    finally:
        await client.aclose()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "retrieval_api_unavailable"
