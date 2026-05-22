import sys
from datetime import timedelta
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
from app.models.schedule import SchedulerRuntimeHeartbeat
import app.services.runtime_capabilities_service as service_module
import app.services.scheduler_runtime as scheduler_runtime_module
from app.services.runtime_capabilities_service import build_runtime_capabilities
from app.utils.time import utc_now

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


def _build_scheduler_runtime_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[SchedulerRuntimeHeartbeat.__table__],
    )
    return sessionmaker(bind=engine)


def _write_scheduler_heartbeat(Session, *, last_heartbeat_at, last_reconcile_at=None, status="running"):
    with Session() as db:
        db.add(
            SchedulerRuntimeHeartbeat(
                id=1,
                owner="scheduler-worker",
                worker_name="scheduler-worker",
                started_at=utc_now(),
                last_heartbeat_at=last_heartbeat_at,
                status=status,
                active_schedule_count=3,
                registered_job_count=3,
                last_reconcile_at=last_reconcile_at,
                last_error=None,
            )
        )
        db.commit()


def test_get_scheduler_runtime_status_reports_missing_fresh_and_stale_heartbeats(monkeypatch):
    Session = _build_scheduler_runtime_session()
    stale_after_seconds = 60

    monkeypatch.setattr(scheduler_runtime_module, "SessionLocal", Session)
    monkeypatch.setattr(
        scheduler_runtime_module.settings,
        "scheduler_heartbeat_stale_seconds",
        stale_after_seconds,
    )

    missing = scheduler_runtime_module.get_scheduler_runtime_status()

    assert missing["available"] is False
    assert missing["manual_run_available"] is True
    assert missing["owner"] == "scheduler-worker"
    assert missing["heartbeat_status"] == "missing"
    assert missing["reason"] == "scheduler_worker_missing"

    fresh_now = utc_now()
    _write_scheduler_heartbeat(
        Session,
        last_heartbeat_at=fresh_now,
        last_reconcile_at=fresh_now,
    )

    fresh = scheduler_runtime_module.get_scheduler_runtime_status()

    assert fresh["available"] is True
    assert fresh["manual_run_available"] is True
    assert fresh["owner"] == "scheduler-worker"
    assert fresh["worker_name"] == "scheduler-worker"
    assert fresh["heartbeat_status"] == "fresh"
    assert fresh["reason"] is None
    assert fresh["active_schedule_count"] == 3
    assert fresh["registered_job_count"] == 3

    with Session() as db:
        heartbeat = db.query(SchedulerRuntimeHeartbeat).filter(SchedulerRuntimeHeartbeat.id == 1).one()
        heartbeat.last_heartbeat_at = utc_now() - timedelta(seconds=stale_after_seconds + 1)
        db.commit()

    stale = scheduler_runtime_module.get_scheduler_runtime_status()

    assert stale["available"] is False
    assert stale["manual_run_available"] is True
    assert stale["heartbeat_status"] == "stale"
    assert stale["reason"] == "scheduler_worker_stale"
    assert stale["active_schedule_count"] == 3
    assert stale["registered_job_count"] == 3


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
        lambda: {
            "enabled": True,
            "available": True,
            "manual_run_available": True,
            "running": True,
            "owner": "scheduler-worker",
            "worker_name": "scheduler-worker",
            "heartbeat_status": "fresh",
            "last_heartbeat_at": "2026-05-22T00:00:00+00:00",
            "last_reconcile_at": "2026-05-22T00:00:00+00:00",
            "reason": None,
        },
    )
    monkeypatch.setattr(
        service_module,
        "build_operator_health_summary",
        lambda: {"status": "healthy", "workers": {}, "queues": {}, "freshness": {}, "scheduler": {}},
    )

    payload = build_runtime_capabilities()

    assert payload["search"]["lexical"]["available"] is True
    assert payload["search"]["semantic"]["available"] is False
    assert payload["search"]["hybrid"]["reason"] == "retrieval_api_url_not_configured"
    assert payload["recommendations"]["similar_jobs"]["available"] is False
    assert payload["ai"]["jobs"]["available"] is True
    assert payload["scheduler"]["available"] is True
    assert payload["scheduler"]["manual_run_available"] is True
    assert payload["scheduler"]["owner"] == "scheduler-worker"
    assert payload["scheduler"]["heartbeat_status"] == "fresh"
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
        lambda: {
            "enabled": True,
            "available": False,
            "manual_run_available": True,
            "running": False,
            "owner": "scheduler-worker",
            "worker_name": "scheduler-worker",
            "heartbeat_status": "stale",
            "last_heartbeat_at": "2026-05-21T23:58:00+00:00",
            "last_reconcile_at": "2026-05-21T23:57:30+00:00",
            "reason": "scheduler_worker_stale",
        },
    )
    monkeypatch.setattr(
        service_module,
        "build_operator_health_summary",
        lambda: {"status": "healthy", "workers": {}, "queues": {}, "freshness": {}, "scheduler": {}},
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
    assert payload["scheduler"]["available"] is False
    assert payload["scheduler"]["manual_run_available"] is True
    assert payload["scheduler"]["owner"] == "scheduler-worker"
    assert payload["scheduler"]["heartbeat_status"] == "stale"
