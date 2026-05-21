import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.runtime_capabilities_service as service_module
from app.services.runtime_capabilities_service import build_runtime_capabilities


class _RuntimeStatus:
    is_ready = True
    is_degraded = False
    requires_test = False
    configured_provider = "custom"
    model = "deepseek-v4-flash"
    active_fingerprint = "fp-runtime"
    last_tested_fingerprint = "fp-runtime"
    degradation_reason = None
    last_tested_at = None


def test_build_runtime_capabilities_reports_lexical_baseline_without_sidecars(monkeypatch):
    monkeypatch.setattr(service_module.settings, "retrieval_api_url", None)
    monkeypatch.setattr(service_module.settings, "recommendation_api_url", None)
    monkeypatch.setattr(
        service_module,
        "get_profile_runtime_metadata",
        lambda scope: _RuntimeStatus(),
    )
    monkeypatch.setattr(
        service_module,
        "get_scheduler_runtime_status",
        lambda: {"enabled": True, "running": True, "owner": "backend-api"},
    )
    monkeypatch.setattr(
        service_module,
        "build_operator_health_summary",
        lambda: {"status": "healthy", "workers": {}, "queues": {}, "freshness": {}},
    )

    payload = build_runtime_capabilities()

    assert payload["search"]["lexical"]["available"] is True
    assert payload["search"]["semantic"]["available"] is False
    assert payload["search"]["hybrid"]["reason"] == "retrieval_api_url_not_configured"
    assert payload["recommendations"]["similar_jobs"]["available"] is False
    assert payload["ai"]["jobs"]["available"] is True
    assert payload["scheduler"]["available"] is True
    assert payload["sources"]["jobsdb"]["default_crawl_mode"] == "headed"
    assert payload["sources"]["ctgoodjobs"]["manual_action_supported"] is True
