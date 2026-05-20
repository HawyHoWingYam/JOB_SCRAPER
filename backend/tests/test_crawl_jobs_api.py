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
import app.api.progress as progress_module
import app.api.crawl_jobs as crawl_jobs_module

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
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, Session


def _seed_manual_action_crawl_job(
    Session,
    *,
    source_site: str = "ctgoodjobs",
    request_payload: dict | None = None,
    manual_action: dict | None = None,
    status: str = "manual_action_required",
    event_type: str = "crawl.manual_action_required",
):
    crawl_job_id = uuid.uuid4()
    payload = request_payload or {
        "source_site": source_site,
        "category_ids": ["ctgoodjobs:021"],
        "max_pages": 52,
        "crawl_mode": "headed",
        "crawl_phase": "listing",
    }
    manual_action_payload = manual_action or {
        "action_type": "human_verification",
        "source_site": source_site,
        "stage": "category_page",
        "blocked_url": "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52",
        "referer": "https://jobs.ctgoodjobs.hk/jobs",
        "crawl_mode": "headed",
        "browser_channel": "msedge",
        "browser_profile_path": None,
        "resume_supported": True,
        "message": "CTGoodJobs category_page fetch blocked by human verification",
        "instructions": ["Complete the human verification challenge in the headed browser."],
        "resume_context": {
            "crawl_phase": "listing",
            "category_id": "ctgoodjobs:021",
            "page": 52,
            "page_direction": "descending",
        },
    }

    db = Session()
    try:
        crawl_job = CrawlJob(
            id=crawl_job_id,
            source_site=source_site,
            trigger_type="manual",
            status=status,
            request_payload=payload,
            requested_by="api",
            error_message=manual_action_payload["message"],
        )
        db.add(crawl_job)
        db.flush()
        db.add(
            CrawlJobEvent(
                crawl_job_id=crawl_job_id,
                sequence_no=1,
                event_type=event_type,
                payload={
                    "crawl_job_id": str(crawl_job_id),
                    "source_site": source_site,
                    "request_payload": payload,
                    "error": manual_action_payload["message"],
                    "manual_action": manual_action_payload,
                },
                emitted_by="crawl-worker",
            )
        )
        db.commit()
    finally:
        db.close()

    return str(crawl_job_id)


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
            assert crawl_job.request_payload["crawl_mode"] == "headed"
            assert crawl_job.request_payload["crawl_phase"] == "listing"
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
        assert progress_payload["all"][crawl_job_id]["crawl_mode"] == "headed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_crawl_jobs_allows_explicit_headless_mode(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    try:
        response = await client.post(
            "/api/v1/crawl-jobs",
            json={
                "source_site": "jobsdb",
                "category_ids": [1200],
                "max_pages": 3,
                "crawl_mode": "headless",
            },
        )

        assert response.status_code == 202
        crawl_job_id = response.json()["id"]

        db = Session()
        try:
            crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
            outbox_rows = db.query(EventOutbox).all()

            assert crawl_job.request_payload["crawl_mode"] == "headless"
            assert crawl_job.request_payload["crawl_phase"] == "listing"
            assert outbox_rows[0].topic == "stream.crawl.commands"
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_crawl_jobs_defaults_ctgoodjobs_to_headed(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    monkeypatch.setattr(
        crawl_jobs_module,
        "get_source_category_registry",
        lambda: type(
            "Registry",
            (),
            {"list_categories": lambda self, *, source_site=None: [{"id": "ctgoodjobs:021"}]},
        )(),
    )
    try:
        response = await client.post(
            "/api/v1/crawl-jobs",
            json={
                "source_site": "ctgoodjobs",
                "category_ids": ["ctgoodjobs:021"],
                "max_pages": 3,
            },
        )

        assert response.status_code == 202
        crawl_job_id = response.json()["id"]

        db = Session()
        try:
            crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
            outbox_rows = db.query(EventOutbox).all()

            assert crawl_job.request_payload["crawl_mode"] == "headed"
            assert crawl_job.request_payload["crawl_phase"] == "listing"
            assert outbox_rows[0].topic == "stream.crawl.commands.headed"
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_crawl_jobs_accepts_detail_phase_with_target_listing_batch(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    target_listing_crawl_job_id = uuid.uuid4()
    try:
        response = await client.post(
            "/api/v1/crawl-jobs",
            json={
                "source_site": "jobsdb",
                "crawl_phase": "detail",
                "source_listing_crawl_job_id": str(target_listing_crawl_job_id),
                "detail_limit": 15,
            },
        )

        assert response.status_code == 202
        crawl_job_id = response.json()["id"]

        db = Session()
        try:
            crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()

            assert crawl_job.request_payload["crawl_phase"] == "detail"
            assert crawl_job.request_payload["source_listing_crawl_job_id"] == str(target_listing_crawl_job_id)
            assert crawl_job.request_payload["detail_limit"] == 15
        finally:
            db.close()
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


@pytest.mark.asyncio
async def test_resume_crawl_job_requeues_same_job_id(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    crawl_job_id = _seed_manual_action_crawl_job(Session)
    try:
        response = await client.post(f"/api/v1/crawl-jobs/{crawl_job_id}/resume")

        assert response.status_code == 200
        assert response.json()["id"] == crawl_job_id

        db = Session()
        try:
            stored = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
            events = (
                db.query(CrawlJobEvent)
                .filter(CrawlJobEvent.crawl_job_id == stored.id)
                .order_by(CrawlJobEvent.sequence_no.asc())
                .all()
            )
            latest_outbox_row = db.query(EventOutbox).order_by(EventOutbox.id.desc()).first()

            assert stored.status == "dispatching"
            assert stored.error_message is None
            assert [event.event_type for event in events] == [
                "crawl.manual_action_required",
                "crawl.resume_requested",
                "crawl.requested",
            ]
            assert latest_outbox_row.aggregate_id == crawl_job_id
            assert latest_outbox_row.event_type == "crawl.requested"
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_resume_crawl_job_rejects_non_manual_action_status(monkeypatch):
    client, Session = _build_test_client(monkeypatch)
    crawl_job_id = _seed_manual_action_crawl_job(
        Session,
        status="failed",
        event_type="crawl.failed",
    )
    try:
        response = await client.post(f"/api/v1/crawl-jobs/{crawl_job_id}/resume")

        assert response.status_code == 409
    finally:
        await client.aclose()
