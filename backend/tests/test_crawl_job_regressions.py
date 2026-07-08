from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Response

import app.api.crawl_jobs as crawl_jobs_api
import app.services.crawl_job_dispatch_service as dispatch_module
from app.schemas.crawl_job import CrawlJobCreateRequest
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


class _FakeCrawlJobRepository:
    def __init__(self, *, crawl_job, latest_event):
        self._crawl_job = crawl_job
        self._latest_event = latest_event

    def get_crawl_job_by_id(self, db, crawl_job_id):
        return self._crawl_job

    def get_latest_manual_action_event(self, db, crawl_job_id):
        return self._latest_event

    def append_event(self, db, **kwargs):
        return None

    def list_events(self, db, crawl_job_id, event_types=None):
        return []


class _FakeEventOutboxRepository:
    def __init__(self):
        self.enqueued: list[dict] = []

    def enqueue(self, db, **kwargs):
        self.enqueued.append(dict(kwargs))
        return SimpleNamespace()


class _FakeOutboxPublisher:
    def __init__(self):
        self.published_rows: list[object] = []
        self.published_batches: list[int] = []

    def publish_row(self, db, row):
        self.published_rows.append(row)

    def publish_pending_batch(self, db, limit):
        self.published_batches.append(limit)


class _FakeDbSession:
    def __init__(self):
        self.commits = 0
        self.refreshed: list[object] = []

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

class _FakeCrawlJobWriterRepository:
    def __init__(self):
        self.created_jobs: list[object] = []
        self.appended_events: list[dict] = []

    def create_crawl_job(
        self,
        db,
        *,
        source_site,
        trigger_type,
        request_payload,
        requested_by=None,
        schedule_id=None,
        status="queued",
        auto_commit=True,
    ):
        crawl_job = SimpleNamespace(
            id=uuid4(),
            source_site=source_site,
            trigger_type=trigger_type,
            request_payload=dict(request_payload),
            requested_by=requested_by,
            schedule_id=schedule_id,
            status=status,
            queued_at=None,
            completed_at=None,
            error_message=None,
        )
        self.created_jobs.append(crawl_job)
        return crawl_job

    def append_event(self, db, **kwargs):
        self.appended_events.append(dict(kwargs))
        return None


class _FakeScheduleRepository:
    def create_execution(self, db, *, schedule_id, status, auto_commit=False):
        return SimpleNamespace(
            id=uuid4(),
            schedule_id=schedule_id,
            status=status,
            crawl_job_id=None,
            request_payload_snapshot=None,
        )


class _RecordingExecutionLauncher:
    def __init__(self):
        self.launch_calls: list[object] = []

    def should_launch_locally(self, crawl_job):
        return True

    def launch(self, crawl_job):
        self.launch_calls.append(crawl_job)
        return SimpleNamespace(
            launched=True,
            command=["python", f"/app/scripts/{crawl_job.source_site}_standalone_crawl.py"],
        )


class _NoopExecutionLauncher:
    def should_launch_locally(self, crawl_job):
        return True

    def launch(self, crawl_job):
        return SimpleNamespace(launched=True, command=["python", "/app/scripts/noop.py"])


@pytest.mark.asyncio
async def test_create_crawl_job_no_longer_launches_api_local_offertoday_subprocess(monkeypatch):
    popen_called = False
    crawl_job_id = uuid4()

    class _FakeDispatchService:
        def dispatch_manual_crawl_job(self, db, **kwargs):
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    source_site="offertoday",
                    request_payload={},
                )
            )

    def fake_popen(*args, **kwargs):
        nonlocal popen_called
        popen_called = True
        raise AssertionError("API route should not launch source-local subprocesses")

    monkeypatch.setattr(crawl_jobs_api, "dispatch_service", _FakeDispatchService())
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    response = Response()
    request = CrawlJobCreateRequest(
        source_site="offertoday",
        crawl_phase="listing",
        category_ids=[],
        max_pages=None,
    )

    crawl_job = await crawl_jobs_api.create_crawl_job(
        request=request,
        response=response,
        db=object(),
    )

    assert popen_called is False
    assert str(crawl_job.id) == str(crawl_job_id)
    assert response.headers["X-Crawl-Job-Id"] == str(crawl_job_id)


def test_dispatch_manual_crawl_job_launches_local_executor_for_offertoday():
    crawl_job_repository = _FakeCrawlJobWriterRepository()
    event_outbox_repository = _FakeEventOutboxRepository()
    outbox_publisher = _FakeOutboxPublisher()
    execution_launcher = _RecordingExecutionLauncher()
    service = CrawlJobDispatchService(
        crawl_job_repository=crawl_job_repository,
        event_outbox_repository=event_outbox_repository,
        outbox_publisher=outbox_publisher,
        execution_launcher=execution_launcher,
    )

    result = service.dispatch_manual_crawl_job(
        _FakeDbSession(),
        source_site="offertoday",
        crawl_phase="listing",
        category_ids=[118000],
        max_pages=1,
        requested_by="api",
    )

    assert str(execution_launcher.launch_calls[0].id) == str(result.crawl_job.id)
    assert event_outbox_repository.enqueued == []
    assert outbox_publisher.published_rows == []
    assert outbox_publisher.published_batches == []


def test_dispatch_schedule_crawl_job_launches_local_executor_for_jobsdb():
    crawl_job_repository = _FakeCrawlJobWriterRepository()
    event_outbox_repository = _FakeEventOutboxRepository()
    outbox_publisher = _FakeOutboxPublisher()
    execution_launcher = _RecordingExecutionLauncher()
    schedule = SimpleNamespace(
        id=uuid4(),
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode="headed",
        category_ids=[6281],
        keywords=None,
        max_pages=1,
        detail_limit=100,
        location=None,
        last_run_at=None,
    )
    service = CrawlJobDispatchService(
        crawl_job_repository=crawl_job_repository,
        event_outbox_repository=event_outbox_repository,
        outbox_publisher=outbox_publisher,
        schedule_repository=_FakeScheduleRepository(),
        execution_launcher=execution_launcher,
    )

    result = service.dispatch_schedule_crawl_job(
        _FakeDbSession(),
        schedule=schedule,
        requested_by="scheduler-worker",
    )

    assert str(execution_launcher.launch_calls[0].id) == str(result.crawl_job.id)
    assert result.schedule_execution is not None
    assert event_outbox_repository.enqueued == []
    assert outbox_publisher.published_rows == []
    assert outbox_publisher.published_batches == []


def test_resume_crawl_job_uses_crawl_job_source_site_for_headed_worker_check(monkeypatch):
    observed: dict[str, str | None] = {}
    crawl_job = SimpleNamespace(
        id=uuid4(),
        source_site="offertoday",
        status="manual_action_required",
        request_payload={"crawl_mode": "headed", "crawl_phase": "listing"},
        trigger_type="manual",
        schedule_id=None,
        requested_by="api",
        queued_at=None,
        completed_at=None,
        error_message="previous error",
    )
    latest_event = SimpleNamespace(
        payload={
            "manual_action": {
                "resume_supported": True,
                "resume_context": {},
            }
        }
    )

    def fake_ensure_headed_crawl_worker_available(*, crawl_mode, source_site):
        observed["crawl_mode"] = crawl_mode
        observed["source_site"] = source_site

    monkeypatch.setattr(
        dispatch_module,
        "ensure_headed_crawl_worker_available",
        fake_ensure_headed_crawl_worker_available,
    )

    service = CrawlJobDispatchService(
        crawl_job_repository=_FakeCrawlJobRepository(
            crawl_job=crawl_job,
            latest_event=latest_event,
        ),
        event_outbox_repository=_FakeEventOutboxRepository(),
        outbox_publisher=_FakeOutboxPublisher(),
        execution_launcher=_NoopExecutionLauncher(),
    )

    result = service.resume_crawl_job(
        _FakeDbSession(),
        crawl_job_id=crawl_job.id,
        requested_by="api",
    )

    assert result is crawl_job
    assert observed == {
        "crawl_mode": "headed",
        "source_site": "offertoday",
    }


def test_resume_crawl_job_persists_selected_resume_strategy(monkeypatch):
    crawl_job = SimpleNamespace(
        id=uuid4(),
        source_site="offertoday",
        status="manual_action_required",
        request_payload={"crawl_mode": "headed", "crawl_phase": "listing"},
        trigger_type="manual",
        schedule_id=None,
        requested_by="api",
        queued_at=None,
        completed_at=None,
        error_message="previous error",
    )
    latest_event = SimpleNamespace(
        payload={
            "manual_action": {
                "resume_supported": True,
                "resume_context": {"crawl_phase": "listing"},
            }
        }
    )

    monkeypatch.setattr(
        dispatch_module,
        "ensure_headed_crawl_worker_available",
        lambda **kwargs: None,
    )

    service = CrawlJobDispatchService(
        crawl_job_repository=_FakeCrawlJobRepository(
            crawl_job=crawl_job,
            latest_event=latest_event,
        ),
        event_outbox_repository=_FakeEventOutboxRepository(),
        outbox_publisher=_FakeOutboxPublisher(),
        execution_launcher=_NoopExecutionLauncher(),
    )

    result = service.resume_crawl_job(
        _FakeDbSession(),
        crawl_job_id=crawl_job.id,
        requested_by="api",
        strategy="reuse_open_browser",
    )

    assert result is crawl_job
    assert crawl_job.request_payload["resume_strategy"] == "reuse_open_browser"
