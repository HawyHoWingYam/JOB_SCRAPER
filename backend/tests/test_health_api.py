import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.api.health as health_module


@pytest.mark.asyncio
async def test_health_check_returns_degraded_when_job_llm_is_degraded(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "refresh_llm_status",
        lambda scope=None: {
            "is_degraded": scope != "companies",
            "degradation_reason": "llm_unavailable" if scope != "companies" else None,
        },
    )

    payload = await health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["service"] == "backend-api"
    assert payload["issues"] == ["Job LLM: llm_unavailable"]


def test_health_route_returns_healthy_without_operator_payload(monkeypatch):
    app = FastAPI()
    app.include_router(health_module.router)
    monkeypatch.setattr(
        health_module,
        "refresh_llm_status",
        lambda *args: {"is_degraded": False, "degradation_reason": None},
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "backend-api",
    }
