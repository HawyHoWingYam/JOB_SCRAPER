import sys
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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


class _DummyAsyncIOScheduler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.jobs = {}
        self.running = False

    def start(self):
        self.running = True
        return None

    def shutdown(self):
        self.running = False
        return None

    def add_job(self, func, *, trigger, id, args, replace_existing):
        job = SimpleNamespace(
            id=id,
            func=func,
            trigger=trigger,
            args=args,
            replace_existing=replace_existing,
            next_run_time=getattr(trigger, "next_run_time", None),
        )
        self.jobs[id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


class _DummySQLAlchemyJobStore:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _DummyCronTrigger:
    calls = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.expression = kwargs.get("expression")
        self.timezone = kwargs.get("timezone")

    @classmethod
    def from_crontab(cls, expression, timezone=None):
        trigger = cls(expression=expression, timezone=timezone)
        trigger.next_run_time = FIXED_NEXT_RUN_AT
        cls.calls.append(trigger)
        return trigger


apscheduler_module = types.ModuleType("apscheduler")
apscheduler_schedulers_module = types.ModuleType("apscheduler.schedulers")
apscheduler_asyncio_module = types.ModuleType("apscheduler.schedulers.asyncio")
apscheduler_jobstores_module = types.ModuleType("apscheduler.jobstores")
apscheduler_sqlalchemy_module = types.ModuleType("apscheduler.jobstores.sqlalchemy")
apscheduler_triggers_module = types.ModuleType("apscheduler.triggers")
apscheduler_cron_module = types.ModuleType("apscheduler.triggers.cron")

apscheduler_asyncio_module.AsyncIOScheduler = _DummyAsyncIOScheduler
apscheduler_sqlalchemy_module.SQLAlchemyJobStore = _DummySQLAlchemyJobStore
apscheduler_cron_module.CronTrigger = _DummyCronTrigger

sys.modules.setdefault("apscheduler", apscheduler_module)
sys.modules.setdefault("apscheduler.schedulers", apscheduler_schedulers_module)
sys.modules.setdefault("apscheduler.schedulers.asyncio", apscheduler_asyncio_module)
sys.modules.setdefault("apscheduler.jobstores", apscheduler_jobstores_module)
sys.modules.setdefault("apscheduler.jobstores.sqlalchemy", apscheduler_sqlalchemy_module)
sys.modules.setdefault("apscheduler.triggers", apscheduler_triggers_module)
sys.modules.setdefault("apscheduler.triggers.cron", apscheduler_cron_module)

from app.api.schedules import router as schedules_router
import app.api.schedules as schedules_api_module
from app.database import Base, get_db
from app.models import (
    CrawlJob,
    CrawlJobEvent,
    EventOutbox,
    ScrapeSchedule,
    ScheduleExecution,
    SchedulerRuntimeHeartbeat,
)
from app.repositories.schedule_repository import ScheduleRepository
from app.services.scheduler_service import SchedulerService, run_scheduled_crawl_job
import app.services.scheduler_service as scheduler_service_module
from app.utils.time import utc_now

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


FIXED_NEXT_RUN_AT = datetime(2026, 5, 23, 18, 30, tzinfo=UTC)


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
            SchedulerRuntimeHeartbeat.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            EventOutbox.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return engine, Session


def _create_schedule(
    Session,
    *,
    source_site="jobsdb",
    category_ids=None,
    crawl_phase="listing",
    detail_limit=100,
    cron_expression="0 2 * * *",
    timezone="Asia/Hong_Kong",
    is_active=True,
):
    db = Session()
    try:
        schedule = ScrapeSchedule(
            id=uuid.uuid4(),
            name=f"{source_site} nightly",
            cron_expression=cron_expression,
            timezone=timezone,
            source_site=source_site,
            crawl_phase=crawl_phase,
            crawl_mode=None,
            detail_limit=detail_limit,
            category_ids=category_ids if category_ids is not None else [1200],
            max_pages=3,
            is_active=is_active,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        return schedule
    finally:
        db.close()


def _build_schedules_app(Session):
    app = FastAPI()
    app.include_router(schedules_router, prefix="/api/v1")

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return app


def _install_forbidden_scheduler_runtime(monkeypatch):
    async def fail_add(*args, **kwargs):
        raise AssertionError("API routes should not register schedules in-process")

    async def fail_update(*args, **kwargs):
        raise AssertionError("API routes should not update schedules in-process")

    class _ForbiddenSchedulerService:
        @staticmethod
        def get_instance():
            raise AssertionError("API routes should not rely on in-process scheduler runtime")

    monkeypatch.setattr(schedules_api_module, "_add_schedule_to_scheduler", fail_add, raising=False)
    monkeypatch.setattr(schedules_api_module, "_update_schedule_in_scheduler", fail_update, raising=False)
    monkeypatch.setattr(schedules_api_module, "SchedulerService", _ForbiddenSchedulerService, raising=False)


@pytest.mark.asyncio
async def test_schedule_run_endpoint_queues_crawl_job_and_links_execution(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(Session)
    app = _build_schedules_app(Session)

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    _install_forbidden_scheduler_runtime(monkeypatch)
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
            assert crawl_job.request_payload["crawl_mode"] == "headed"
            assert crawl_job.request_payload["crawl_phase"] == "listing"
            assert execution.request_payload_snapshot == crawl_job.request_payload
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
        assert crawl_job.request_payload["crawl_mode"] == "headed"
        assert crawl_job.request_payload["crawl_phase"] == "listing"
        assert execution.request_payload_snapshot == crawl_job.request_payload
        assert events[0].payload["request_payload"] == crawl_job.request_payload
        assert outbox_rows[0].payload["request_payload"] == crawl_job.request_payload
    finally:
        db.close()


@pytest.mark.asyncio
async def test_scheduler_startup_loads_ctgoodjobs_schedules_without_live_registry_validation(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(Session, source_site="ctgoodjobs", category_ids=["ctgoodjobs:021"])

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    service = SchedulerService()
    added_jobs = []

    def fail_if_called(*args, **kwargs):
        raise AssertionError("startup should not perform live CTgoodjobs registry validation")

    def record_add_job(schedule, db=None, **kwargs):
        added_jobs.append((schedule.id, kwargs.get("ctgoodjobs_validated")))

    monkeypatch.setattr(service, "_validate_ctgoodjobs_schedule", fail_if_called)
    monkeypatch.setattr(service, "_add_job", record_add_job)

    await service._load_active_schedules()

    assert added_jobs == [(schedule.id, True)]


@pytest.mark.asyncio
async def test_scheduler_service_dispatches_detail_schedules_with_detail_limit(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(
        Session,
        source_site="jobsdb",
        category_ids=[6281],
        crawl_phase="detail",
        detail_limit=30,
    )

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    service = SchedulerService()

    crawl_job = await service._dispatch_schedule(schedule.id, trigger_type="schedule")

    assert crawl_job is not None
    assert crawl_job.request_payload["crawl_phase"] == "detail"
    assert crawl_job.request_payload["detail_limit"] == 30
    assert crawl_job.request_payload["category_ids"] == [6281]


@pytest.mark.asyncio
async def test_scheduler_reconcile_registers_updates_and_removes_active_schedules(monkeypatch):
    _DummyCronTrigger.calls.clear()
    _engine, Session = _build_engine_and_session()
    primary_schedule = _create_schedule(Session)
    secondary_schedule = _create_schedule(
        Session,
        source_site="jobsdb",
        category_ids=[6281],
        cron_expression="15 1 * * *",
        timezone="Asia/Hong_Kong",
    )

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    service = SchedulerService()
    service.scheduler = _DummyAsyncIOScheduler()
    service.scheduler.start()
    monkeypatch.setattr(service, "_write_runtime_heartbeat", lambda *args, **kwargs: None, raising=False)

    await service.reconcile_schedules()

    assert set(service.scheduler.jobs) == {
        str(primary_schedule.id),
        str(secondary_schedule.id),
    }
    assert service.scheduler.jobs[str(primary_schedule.id)].func is run_scheduled_crawl_job
    assert service.scheduler.jobs[str(primary_schedule.id)].args == [str(primary_schedule.id)]
    assert service.scheduler.jobs[str(secondary_schedule.id)].func is run_scheduled_crawl_job
    assert service.scheduler.jobs[str(secondary_schedule.id)].args == [str(secondary_schedule.id)]

    db = Session()
    try:
        repository = ScheduleRepository()
        refreshed_primary = repository.get_schedule_by_id(db, primary_schedule.id)
        refreshed_secondary = repository.get_schedule_by_id(db, secondary_schedule.id)
        expected_next_run_at = FIXED_NEXT_RUN_AT.replace(tzinfo=None)

        assert refreshed_primary.next_run_at == expected_next_run_at
        assert refreshed_secondary.next_run_at == expected_next_run_at

        repository.update_schedule(
            db,
            primary_schedule.id,
            {
                "cron_expression": "45 4 * * *",
                "timezone": "UTC",
            },
        )
        repository.update_schedule(db, secondary_schedule.id, {"is_active": False})
    finally:
        db.close()

    await service.reconcile_schedules()

    assert set(service.scheduler.jobs) == {str(primary_schedule.id)}
    updated_job = service.scheduler.get_job(str(primary_schedule.id))
    assert updated_job is not None
    assert updated_job.trigger.expression == "45 4 * * *"
    assert getattr(updated_job.trigger.timezone, "key", str(updated_job.trigger.timezone)) == "UTC"

    db = Session()
    try:
        repository = ScheduleRepository()
        refreshed_primary = repository.get_schedule_by_id(db, primary_schedule.id)
        refreshed_secondary = repository.get_schedule_by_id(db, secondary_schedule.id)

        assert refreshed_primary.next_run_at == FIXED_NEXT_RUN_AT.replace(tzinfo=None)
        assert refreshed_secondary.next_run_at is None
    finally:
        db.close()


@pytest.mark.asyncio
async def test_schedule_crud_endpoints_do_not_call_in_process_scheduler(monkeypatch):
    _engine, Session = _build_engine_and_session()
    app = _build_schedules_app(Session)
    _install_forbidden_scheduler_runtime(monkeypatch)

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        create_response = await client.post(
            "/api/v1/schedules",
            json={
                "name": "jobsdb nightly",
                "cron_expression": "0 2 * * *",
                "timezone": "Asia/Hong_Kong",
                "source_site": "jobsdb",
                "crawl_phase": "listing",
                "crawl_mode": "headed",
                "category_ids": [1200],
                "max_pages": 3,
                "detail_limit": 100,
            },
        )
        assert create_response.status_code == 200
        schedule_id = create_response.json()["id"]

        update_response = await client.put(
            f"/api/v1/schedules/{schedule_id}",
            json={
                "name": "jobsdb refreshed",
                "cron_expression": "15 3 * * *",
            },
        )
        assert update_response.status_code == 200

        toggle_response = await client.post(f"/api/v1/schedules/{schedule_id}/toggle")
        assert toggle_response.status_code == 200

        delete_response = await client.delete(f"/api/v1/schedules/{schedule_id}")
        assert delete_response.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_schedule_history_route_returns_request_payload_snapshot(monkeypatch):
    _engine, Session = _build_engine_and_session()
    schedule = _create_schedule(Session, source_site="ctgoodjobs", category_ids=["ctgoodjobs:021"])
    app = _build_schedules_app(Session)

    monkeypatch.setattr(scheduler_service_module, "SessionLocal", Session)
    _install_forbidden_scheduler_runtime(monkeypatch)
    SchedulerService._instance = None

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        run_response = await client.post(f"/api/v1/schedules/{schedule.id}/run")
        assert run_response.status_code == 202
        run_payload = run_response.json()

        history_response = await client.get(f"/api/v1/schedules/{schedule.id}/history")

        assert history_response.status_code == 200
        execution = history_response.json()["executions"][0]
        assert execution["crawl_job_id"] == run_payload["id"]
        assert execution["request_payload_snapshot"] == run_payload["request_payload"]
    finally:
        await client.aclose()
        SchedulerService._instance = None


@pytest.mark.asyncio
async def test_immediate_run_now_allows_ctgoodjobs_detail_batch_without_categories(monkeypatch):
    _engine, Session = _build_engine_and_session()
    source_listing_crawl_job_id = uuid.uuid4()
    captured = {}

    app = _build_schedules_app(Session)

    def dispatch_manual_crawl_job(db, **kwargs):
        captured.update(kwargs)
        now = utc_now()
        crawl_job = CrawlJob(
            id=uuid.uuid4(),
            source_site=kwargs["source_site"],
            trigger_type="manual",
            schedule_id=None,
            status="queued",
            request_payload={
                "source_site": kwargs["source_site"],
                "crawl_phase": kwargs["crawl_phase"],
                "crawl_mode": kwargs["crawl_mode"],
                "category_ids": kwargs["category_ids"],
                "source_listing_crawl_job_id": str(kwargs["source_listing_crawl_job_id"]),
                "detail_limit": kwargs["detail_limit"],
            },
            requested_by=kwargs["requested_by"],
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        return SimpleNamespace(crawl_job=crawl_job)

    monkeypatch.setattr(
        schedules_api_module.crawl_job_dispatch_service,
        "dispatch_manual_crawl_job",
        dispatch_manual_crawl_job,
    )

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        response = await client.post(
            "/api/v1/schedules/run-now",
            json={
                "source_site": "ctgoodjobs",
                "crawl_phase": "detail",
                "crawl_mode": "headed",
                "source_listing_crawl_job_id": str(source_listing_crawl_job_id),
                "detail_limit": 200,
            },
        )

        assert response.status_code == 202
        assert captured["source_site"] == "ctgoodjobs"
        assert captured["crawl_phase"] == "detail"
        assert captured["category_ids"] == []
        assert captured["source_listing_crawl_job_id"] == source_listing_crawl_job_id
    finally:
        await client.aclose()
