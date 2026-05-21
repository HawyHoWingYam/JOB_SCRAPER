import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import router as api_router
from app.database import Base
from app.models.app_runtime_settings import AppRuntimeSettings
import app.services.runtime_capabilities_service as service_module
from app.services.runtime_capabilities_service import build_runtime_capabilities

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


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


def _build_runtime_settings_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[AppRuntimeSettings.__table__],
    )
    return sessionmaker(bind=engine)


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


def test_get_profile_runtime_metadata_does_not_flush_when_settings_row_is_absent(monkeypatch):
    Session = _build_runtime_settings_session()
    flushes = []

    event.listen(Session, "before_flush", lambda *_args: flushes.append(True))
    monkeypatch.setattr(service_module, "SessionLocal", Session)

    metadata = service_module.get_profile_runtime_metadata("jobs")

    assert flushes == []
    assert metadata.is_ready is False
    assert metadata.configured_provider is None
    assert metadata.degradation_reason == "profile_not_configured"
    with Session() as db:
        assert db.query(AppRuntimeSettings).count() == 0


@pytest.mark.asyncio
async def test_get_capabilities_route_returns_contract(monkeypatch):
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
    app = FastAPI()
    app.include_router(api_router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["search"]["lexical"]["available"] is True
    assert payload["search"]["semantic"]["available"] is False
    assert payload["ai"]["jobs"]["provider"] == "custom"
