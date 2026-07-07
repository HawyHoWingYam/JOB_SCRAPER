from __future__ import annotations

import subprocess
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
    def enqueue(self, db, **kwargs):
        return SimpleNamespace()


class _FakeOutboxPublisher:
    def publish_row(self, db, row):
        return None

    def publish_pending_batch(self, db, limit):
        return None


class _FakeDbSession:
    def commit(self):
        return None

    def refresh(self, obj):
        return None


@pytest.mark.asyncio
async def test_create_crawl_job_uses_resolved_max_pages_for_offertoday_subprocess(monkeypatch):
    subprocess_calls: list[list[str]] = []
    crawl_job_id = uuid4()

    class _FakeDispatchService:
        def dispatch_manual_crawl_job(self, db, **kwargs):
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    request_payload={"max_pages": 50},
                )
            )

    def fake_popen(args, stdout=None, stderr=None):
        subprocess_calls.append(list(args))
        return SimpleNamespace()

    monkeypatch.setattr(crawl_jobs_api, "dispatch_service", _FakeDispatchService())
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    request = CrawlJobCreateRequest(
        source_site="offertoday",
        crawl_phase="listing",
        category_ids=[],
        max_pages=None,
    )

    await crawl_jobs_api.create_crawl_job(
        request=request,
        response=Response(),
        db=object(),
    )

    assert subprocess_calls, "expected OfferToday subprocess to be launched"
    assert "--max-pages" in subprocess_calls[0]
    assert subprocess_calls[0][subprocess_calls[0].index("--max-pages") + 1] == "50"


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
