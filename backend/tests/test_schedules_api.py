from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import schedules
from app.database import get_db


def _build_schedule(name: str):
    now = datetime(2026, 5, 28, 9, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=None,
        cron_expression="0 2 * * *",
        timezone="Asia/Hong_Kong",
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode="headed",
        category_ids=[1200],
        keywords=None,
        location="Hong Kong",
        max_pages=3,
        detail_limit=100,
        is_active=True,
        last_run_at=None,
        next_run_at=None,
        latest_execution_status=None,
        latest_execution_started_at=None,
        latest_execution_completed_at=None,
        latest_execution_jobs_scraped=None,
        latest_execution_jobs_saved=None,
        created_at=now,
        updated_at=now,
    )


def _build_execution(*, schedule_id, status: str, started_at: str):
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return SimpleNamespace(
        id=uuid4(),
        schedule_id=schedule_id,
        crawl_job_id=None,
        status=status,
        started_at=started,
        completed_at=started,
        duration_seconds=60,
        jobs_scraped=10,
        jobs_saved=8,
        phase1_completed=True,
        phase2_completed=False,
        phase3_completed=False,
        phase4_completed=False,
        phase5_completed=False,
        ids_collected=12,
        jobs_classified=0,
        error_message=None,
        request_payload_snapshot={},
        created_at=started,
    )


class FakeScheduleRepository:
    def __init__(self, *, schedules_list, executions=None, execution_total=None):
        self.schedules_list = list(schedules_list)
        self.executions = list(executions or [])
        self.execution_total = execution_total
        self.count_calls = 0
        self.execution_count_calls = 0

    def get_all_schedules(self, db, skip=0, limit=100):
        return list(self.schedules_list)

    def count_schedules(self, db):
        self.count_calls += 1
        raise AssertionError("count_schedules() should be skipped when a short first page proves the total")

    def get_schedule_by_id(self, db, schedule_id):
        return next((schedule for schedule in self.schedules_list if schedule.id == schedule_id), None)

    def get_executions(self, db, schedule_id, limit=20):
        return list(self.executions)

    def count_executions(self, db, schedule_id):
        self.execution_count_calls += 1
        if self.execution_total is None:
            raise AssertionError("count_executions() should be skipped when a short history page proves the total")
        return self.execution_total


def test_list_schedules_skips_total_count_for_short_first_page(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    repository = FakeScheduleRepository(
        schedules_list=[
            _build_schedule("JobsDB Nightly"),
            _build_schedule("CTgoodjobs Nightly"),
        ]
    )
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get("/api/v1/schedules?skip=0&limit=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [schedule["name"] for schedule in payload["schedules"]] == [
        "JobsDB Nightly",
        "CTgoodjobs Nightly",
    ]


def test_list_schedules_skips_total_count_for_short_later_page(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    repository = FakeScheduleRepository(
        schedules_list=[
            _build_schedule("Batch 26"),
            _build_schedule("Batch 27"),
        ]
    )
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get("/api/v1/schedules?skip=25&limit=25")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 27
    assert [schedule["name"] for schedule in payload["schedules"]] == ["Batch 26", "Batch 27"]


def test_list_schedules_exposes_latest_execution_summary_fields(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    schedule = _build_schedule("JobsDB Nightly")
    schedule.latest_execution_status = "completed_with_ai_failures"
    schedule.latest_execution_started_at = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
    schedule.latest_execution_completed_at = datetime(2026, 5, 28, 8, 5, tzinfo=UTC)
    schedule.latest_execution_jobs_scraped = 12
    schedule.latest_execution_jobs_saved = 11
    repository = FakeScheduleRepository(schedules_list=[schedule])
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get("/api/v1/schedules?skip=0&limit=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedules"][0]["latest_execution_status"] == "completed_with_ai_failures"
    assert payload["schedules"][0]["latest_execution_jobs_scraped"] == 12
    assert payload["schedules"][0]["latest_execution_jobs_saved"] == 11


def test_list_schedules_exposes_latest_execution_running_detail_counts(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    schedule = _build_schedule("JobsDB Recovery In Flight")
    schedule.latest_execution_status = "running"
    schedule.latest_execution_started_at = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
    schedule.latest_execution_jobs_scraped = 0
    schedule.latest_execution_jobs_saved = 0
    schedule.latest_execution_listings_staged = 96
    schedule.latest_execution_detail_pending = 51
    schedule.latest_execution_detail_running = 12
    schedule.latest_execution_detail_completed = 22
    repository = FakeScheduleRepository(schedules_list=[schedule])
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get("/api/v1/schedules?skip=0&limit=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedules"][0]["latest_execution_listings_staged"] == 96
    assert payload["schedules"][0]["latest_execution_detail_pending"] == 51
    assert payload["schedules"][0]["latest_execution_detail_running"] == 12
    assert payload["schedules"][0]["latest_execution_detail_completed"] == 22


def test_schedule_history_skips_total_count_for_short_result_page(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    schedule = _build_schedule("JobsDB Nightly")
    repository = FakeScheduleRepository(
        schedules_list=[schedule],
        executions=[
            _build_execution(
                schedule_id=schedule.id,
                status="completed",
                started_at="2026-05-28T08:00:00Z",
            ),
            _build_execution(
                schedule_id=schedule.id,
                status="failed",
                started_at="2026-05-27T08:00:00Z",
            ),
        ],
    )
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get(f"/api/v1/schedules/{schedule.id}/history?limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [execution["status"] for execution in payload["executions"]] == ["completed", "failed"]


def test_schedule_history_uses_true_total_when_result_page_is_full(monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router, prefix="/api/v1")
    schedule = _build_schedule("JobsDB Nightly")
    repository = FakeScheduleRepository(
        schedules_list=[schedule],
        executions=[
            _build_execution(
                schedule_id=schedule.id,
                status="completed",
                started_at="2026-05-28T08:00:00Z",
            ),
            _build_execution(
                schedule_id=schedule.id,
                status="failed",
                started_at="2026-05-27T08:00:00Z",
            ),
        ],
        execution_total=7,
    )
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(schedules, "repository", repository)
    client = TestClient(app)

    response = client.get(f"/api/v1/schedules/{schedule.id}/history?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 7
    assert repository.execution_count_calls == 1
