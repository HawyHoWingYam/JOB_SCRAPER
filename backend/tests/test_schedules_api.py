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
        created_at=now,
        updated_at=now,
    )


class FakeScheduleRepository:
    def __init__(self, *, schedules_list):
        self.schedules_list = list(schedules_list)
        self.count_calls = 0

    def get_all_schedules(self, db, skip=0, limit=100):
        return list(self.schedules_list)

    def count_schedules(self, db):
        self.count_calls += 1
        raise AssertionError("count_schedules() should be skipped when a short first page proves the total")


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
