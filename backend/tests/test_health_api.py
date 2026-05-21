import sys
from pathlib import Path

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
        health_module,
        "build_operator_health_summary",
        lambda: {
            "status": "critical",
            "issues": ["ingest-worker is down", "stream.job.ingest lag is 5764"],
            "workers": {"ingest-worker": {"status": "down"}},
            "queues": {"stream.job.ingest": {"lag": 5764}},
            "freshness": {"jobs": {"newest_updated_at": "2026-05-20T13:40:46"}},
        },
    )

    payload = await health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["service"] == "backend-api"
    assert payload["operator"]["status"] == "critical"
    assert "ingest-worker is down" in payload["issues"]
    assert "stream.job.ingest lag is 5764" in payload["issues"]
