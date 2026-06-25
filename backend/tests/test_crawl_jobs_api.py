from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import crawl_jobs
from app.database import get_db


def _build_crawl_job():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        source_site="jobsdb",
        trigger_type="manual",
        schedule_id=None,
        status="completed",
        request_payload={"crawl_phase": "listing", "crawl_mode": "headed"},
        requested_by="tester",
        queued_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
        metrics=None,
        created_at=now,
        updated_at=now,
    )


def _build_event(*, crawl_job_id, sequence_no: int, event_type: str):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=sequence_no,
        crawl_job_id=crawl_job_id,
        sequence_no=sequence_no,
        event_type=event_type,
        payload={"sequence_no": sequence_no},
        emitted_by="tester",
        created_at=now,
    )


class FakeCrawlJobRepository:
    def __init__(self, *, crawl_job, events: list[object], total: int) -> None:
        self.crawl_job = crawl_job
        self.events = list(events)
        self.total = total
        self.list_events_calls: list[dict[str, object]] = []
        self.count_events_calls: list[dict[str, object]] = []

    def get_crawl_job_by_id(self, db, crawl_job_id):
        if crawl_job_id == self.crawl_job.id:
            return self.crawl_job
        return None

    def count_events(self, db, crawl_job_id, event_types=None):
        self.count_events_calls.append(
            {
                "crawl_job_id": crawl_job_id,
                "event_types": event_types,
            }
        )
        return self.total

    def list_events(
        self,
        db,
        crawl_job_id,
        event_types=None,
        limit=None,
        tail=False,
    ):
        self.list_events_calls.append(
            {
                "crawl_job_id": crawl_job_id,
                "event_types": event_types,
                "limit": limit,
                "tail": tail,
            }
        )
        return list(self.events)


def _build_client(monkeypatch, repository):
    app = FastAPI()
    app.include_router(crawl_jobs.router, prefix="/api/v1")
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(crawl_jobs, "crawl_job_repository", repository)
    return TestClient(app)


def test_list_crawl_job_events_returns_bounded_tail_with_total(monkeypatch):
    crawl_job = _build_crawl_job()
    repository = FakeCrawlJobRepository(
        crawl_job=crawl_job,
        events=[
            _build_event(crawl_job_id=crawl_job.id, sequence_no=249, event_type="crawl.page_processed"),
            _build_event(crawl_job_id=crawl_job.id, sequence_no=250, event_type="crawl.completed"),
        ],
        total=250,
    )
    client = _build_client(monkeypatch, repository)

    response = client.get(f"/api/v1/crawl-jobs/{crawl_job.id}/events?limit=2")

    assert response.status_code == 200
    assert repository.count_events_calls == [
        {
            "crawl_job_id": crawl_job.id,
            "event_types": None,
        }
    ]
    assert repository.list_events_calls == [
        {
            "crawl_job_id": crawl_job.id,
            "event_types": None,
            "limit": 2,
            "tail": True,
        }
    ]
    assert response.json()["total"] == 250
    assert [event["sequence_no"] for event in response.json()["events"]] == [249, 250]


def test_create_crawl_job_returns_service_unavailable_when_headed_worker_is_offline(monkeypatch):
    class HeadedWorkerUnavailableError(RuntimeError):
        pass

    class FakeDispatchService:
        def dispatch_manual_crawl_job(self, *args, **kwargs):
            raise HeadedWorkerUnavailableError(
                "Headed crawl worker is unavailable. Start python backend\\scripts\\prepare_headed_crawl_worker_host.py and retry."
            )

    async def fake_validate_effective_category_ids(source_site, category_ids):
        return None

    app = FastAPI()
    app.include_router(crawl_jobs.router, prefix="/api/v1")
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(crawl_jobs, "dispatch_service", FakeDispatchService())
    monkeypatch.setattr(crawl_jobs, "_validate_effective_category_ids", fake_validate_effective_category_ids)
    monkeypatch.setattr(
        crawl_jobs,
        "HeadedCrawlWorkerUnavailableError",
        HeadedWorkerUnavailableError,
        raising=False,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/crawl-jobs",
        json={
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headed",
            "category_ids": [1200],
            "max_pages": 3,
            "detail_limit": 100,
            "skip_existing": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Headed crawl worker is unavailable. Start python backend\\scripts\\prepare_headed_crawl_worker_host.py and retry."
    )
