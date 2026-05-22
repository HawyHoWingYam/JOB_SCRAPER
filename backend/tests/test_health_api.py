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
async def test_health_check_includes_operator_runtime_summary(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "refresh_llm_status",
        lambda *args: {"is_degraded": False, "degradation_reason": None},
    )
    monkeypatch.setattr(
        health_module.operator_health_service,
        "build_operator_health_summary",
        lambda: {
            "status": "critical",
            "issues": ["ingest-worker is down", "stream.job.ingest lag is 5764"],
            "workers": {"ingest-worker": {"status": "down"}},
            "queues": {"stream.job.ingest": {"lag": 5764}},
            "freshness": {"jobs": {"newest_updated_at": "2026-05-20T13:40:46"}},
            "scheduler": {
                "owner": "scheduler-worker",
                "heartbeat_status": "stale",
                "reason": "scheduler_worker_stale",
            },
        },
    )

    payload = await health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["service"] == "backend-api"
    assert payload["operator"]["status"] == "critical"
    assert payload["operator"]["scheduler"]["heartbeat_status"] == "stale"
    assert "ingest-worker is down" in payload["issues"]
    assert "stream.job.ingest lag is 5764" in payload["issues"]


def test_health_route_returns_operator_summary_from_service(monkeypatch):
    app = FastAPI()
    app.include_router(health_module.router)
    operator_summary = {
        "status": "healthy",
        "issues": [],
        "workers": {"scheduler-worker": {"status": "healthy"}},
        "queues": {},
        "freshness": {"jobs": {"total": 0, "newest_updated_at": None}},
        "scheduler": {"owner": "scheduler-worker", "heartbeat_status": "fresh", "available": True},
        "headed_runtime": {
            "configured": True,
            "browser_channel": "msedge",
            "browser_user_data_dir_configured": True,
            "browser_user_data_dir_exists": True,
            "lock_port": 47651,
            "worker_group": "crawl-headed-workers",
            "worker_status": "healthy",
            "reason": None,
        },
        "backlogs": {
            "pending_detail_rows": 0,
            "failed_detail_rows": 0,
            "manual_action_detail_rows": 0,
            "outbox_pending": 0,
            "outbox_failed": 0,
            "dead_letter_count": 0,
            "missing_current_embeddings": 0,
            "ai_backlog_jobs": 0,
        },
        "generated_at": "2026-05-22T03:04:05+00:00",
    }
    monkeypatch.setattr(
        health_module,
        "refresh_llm_status",
        lambda *args: {"is_degraded": False, "degradation_reason": None},
    )
    monkeypatch.setattr(
        health_module.operator_health_service,
        "build_operator_health_summary",
        lambda: operator_summary,
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "backend-api",
        "operator": operator_summary,
    }
