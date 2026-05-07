import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import retrieval as retrieval_api
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
    app.include_router(retrieval_api.router, prefix="/api/v1")

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_internal_retrieval_search_uses_local_retrieval_service(monkeypatch):
    client = _build_test_client()
    captured = {}

    class FakeRetrievalService:
        def __init__(self, db):
            captured["db"] = db

        def search(self, request, *, layer_summaries=None):
            captured["request"] = request
            captured["layer_summaries"] = layer_summaries
            return SEARCH_RESPONSE

    monkeypatch.setattr(retrieval_api, "RetrievalService", FakeRetrievalService)
    try:
        response = await client.post(
            "/api/v1/internal/jobs/search",
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
    assert captured["request"].retrieval_mode == "semantic"
    assert captured["layer_summaries"][0].label == "Broad: platform"
