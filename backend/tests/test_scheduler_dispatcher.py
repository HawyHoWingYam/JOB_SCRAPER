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

from app.api.schedules import router as schedules_router
from app.database import Base, get_db
from app.models import CrawlJob, CrawlJobEvent, EventOutbox, ScrapeSchedule, ScheduleExecution
from app.services.progress_store import get_progress_store
from app.services.scheduler_service import SchedulerService
import app.services.scheduler_service as scheduler_service_module

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_engine_and_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            EventOutbox.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    get_progress_store()._progress.clear()
    return engine, Session


def _create_schedule(Session, *, source_site="jobsdb", category_ids=None):
    db = Session()
    try:
        schedule = ScrapeSchedule(
            id=uuid.uuid4(),
            name=f"{source_site} nightly",
            cron_expression="0 2 * * *",
            timezone="Asia/Hong_Kong",
            source_site=source_site,
            category_ids=category_ids if category_ids is not None else [1200],
            max_pages=3,
            is_active=True,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        return schedule
    finally:
        db.close()


@pytest.mark.asyncio
async def test_schedule_run_endpoint_queues_crawl_job_and_links_execution(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(Session)

    app = FastAPI()
    app.include_router(schedules_router, prefix="/api/v1")

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    SchedulerService._instance = None

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        response = await client.post(f"/api/v1/schedules/{schedule.id}/run")

        assert response.status_code == 202
        payload = response.json()
        assert payload["schedule_id"] == str(schedule.id)
        assert payload["trigger_type"] == "manual"

        db = Session()
        try:
            execution = db.query(ScheduleExecution).filter(ScheduleExecution.schedule_id == schedule.id).one()
            crawl_job = db.query(CrawlJob).filter(CrawlJob.id == execution.crawl_job_id).one()

            assert execution.status == "pending"
            assert crawl_job.id == execution.crawl_job_id
            assert crawl_job.status == "queued"
            assert crawl_job.trigger_type == "manual"
        finally:
            db.close()
    finally:
        await client.aclose()
        SchedulerService._instance = None


@pytest.mark.asyncio
async def test_scheduler_service_dispatches_cron_runs_into_durable_control_plane(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(Session, source_site="ctgoodjobs", category_ids=["ctgoodjobs:021"])

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    service = SchedulerService()

    crawl_job = await service._dispatch_schedule(schedule.id, trigger_type="schedule")

    assert crawl_job is not None
    assert crawl_job.trigger_type == "schedule"

    db = Session()
    try:
        execution = db.query(ScheduleExecution).filter(ScheduleExecution.schedule_id == schedule.id).one()
        events = (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == execution.crawl_job_id)
            .order_by(CrawlJobEvent.sequence_no.asc())
            .all()
        )
        outbox_rows = db.query(EventOutbox).all()

        assert execution.status == "pending"
        assert execution.crawl_job_id == crawl_job.id
        assert [event.event_type for event in events] == ["crawl.requested"]
        assert outbox_rows[0].event_type == "crawl.requested"
    finally:
        db.close()
