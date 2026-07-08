from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
import pytest

import app.api.schedules as schedules_api


pytestmark = pytest.mark.filterwarnings(
    r"ignore:Please use `import python_multipart` instead\.:PendingDeprecationWarning"
)


@pytest.mark.asyncio
async def test_run_schedule_now_logs_request_aware_created_summary_from_dispatched_payload(
    monkeypatch,
    caplog,
):
    supplied_db = object()
    schedule_id = uuid4()
    crawl_job_id = uuid4()
    now = datetime.now(timezone.utc)
    schedule = SimpleNamespace(
        id=schedule_id,
        source_site="jobsdb",
        category_ids=["cat-1"],
    )

    class _FakeDispatchService:
        def dispatch_schedule_crawl_job(self, db, **kwargs):
            assert db is supplied_db
            assert kwargs["schedule"] is schedule
            assert kwargs["requested_by"] == "api"
            assert kwargs["trigger_type"] == "manual"
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    source_site="jobsdb",
                    crawl_phase=None,
                    crawl_mode=None,
                    trigger_type="schedule",
                    schedule_id=schedule_id,
                    status="queued",
                    request_payload={
                        "crawl_phase": "detail",
                        "crawl_mode": "headed",
                        "max_pages": 99,
                        "category_ids": ["cat-1", "cat-2"],
                        "source_listing_crawl_job_id": "listing-batch-9",
                    },
                    requested_by="api",
                    queued_at=now,
                    started_at=None,
                    completed_at=None,
                    error_message=None,
                    metrics=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def fake_validate_effective_category_ids(source_site, category_ids):
        return None

    app = FastAPI()

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = "req-schedule-1"
        return await call_next(request)

    app.include_router(schedules_api.router, prefix="/api/v1")
    app.dependency_overrides[schedules_api.get_db] = lambda: supplied_db

    monkeypatch.setattr(
        schedules_api.repository,
        "get_schedule_by_id",
        lambda db, schedule_id_value: schedule,
    )
    monkeypatch.setattr(
        schedules_api,
        "crawl_job_dispatch_service",
        _FakeDispatchService(),
    )
    monkeypatch.setattr(
        schedules_api,
        "_validate_effective_category_ids",
        fake_validate_effective_category_ids,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        with caplog.at_level(logging.INFO):
            response = await client.post(f"/api/v1/schedules/{schedule_id}/run")

    assert response.status_code == 202
    assert (
        "SCRAPE_REQUEST_CREATED request_id=req-schedule-1 source=jobsdb "
        f"crawl_job_id={crawl_job_id} trigger=schedule schedule_id={schedule_id} "
        "phase=detail mode=headed max_pages=99 categories=2 "
        "source_listing_crawl_job_id=listing-batch-9"
    ) in caplog.text
