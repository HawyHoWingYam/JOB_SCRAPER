import sys
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.crawl_jobs import router as crawl_jobs_router
from app.api.progress import router as progress_router
from app.database import Base, get_db
from app.models import CrawlJob, CrawlJobEvent, EventOutbox, ScrapeSchedule, ScheduleExecution
from app.services.progress_store import get_progress_store
import app.api.progress as progress_module

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_test_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            EventOutbox.__table__,
            ScheduleExecution.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(crawl_jobs_router, prefix="/api/v1")
    app.include_router(progress_router, prefix="/api/v1")

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(progress_module, "SessionLocal", Session)
    get_progress_store()._progress.clear()
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, Session


@pytest.mark.asyncio
async def test_post_crawl_jobs_creates_durable_rows_and_exposes_progress(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    try:
        response = await client.post(
            "/api/v1/crawl-jobs",
            json={
                "source_site": "jobsdb",
                "category_ids": [1200],
                "max_pages": 3,
            },
        )

        assert response.status_code == 202
        payload = response.json()
        crawl_job_id = payload["id"]

        db = Session()
        try:
            crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
            events = (
                db.query(CrawlJobEvent)
                .filter(CrawlJobEvent.crawl_job_id == crawl_job.id)
                .order_by(CrawlJobEvent.sequence_no.asc())
                .all()
            )
            outbox_rows = db.query(EventOutbox).all()

            assert crawl_job.status == "queued"
            assert crawl_job.trigger_type == "manual"
            assert crawl_job.request_payload["category_ids"] == [1200]
            assert [event.event_type for event in events] == ["crawl.requested"]
            assert events[0].sequence_no == 1
            assert len(outbox_rows) == 1
            assert outbox_rows[0].event_type == "crawl.requested"
        finally:
            db.close()

        progress_response = await client.get("/api/v1/scrape/progress")

        assert progress_response.status_code == 200
        progress_payload = progress_response.json()
        assert progress_payload["has_active"] is True
        assert progress_payload["all"][crawl_job_id]["status"] == "queued"
        assert progress_payload["all"][crawl_job_id]["crawl_job_id"] == crawl_job_id
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cancel_crawl_job_updates_status_and_event_history(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    try:
        created = await client.post(
            "/api/v1/crawl-jobs",
            json={
                "source_site": "jobsdb",
                "category_ids": [1200],
                "max_pages": 3,
            },
        )
        crawl_job_id = created.json()["id"]

        cancel_response = await client.post(f"/api/v1/crawl-jobs/{crawl_job_id}/cancel")
        events_response = await client.get(f"/api/v1/crawl-jobs/{crawl_job_id}/events")
        get_response = await client.get(f"/api/v1/crawl-jobs/{crawl_job_id}")

        assert cancel_response.status_code == 200
        assert get_response.status_code == 200
        assert events_response.status_code == 200
        assert get_response.json()["status"] == "cancelled"
        assert [event["event_type"] for event in events_response.json()["events"]] == [
            "crawl.requested",
            "crawl.cancelled",
        ]
        assert [event["sequence_no"] for event in events_response.json()["events"]] == [1, 2]
    finally:
        await client.aclose()
