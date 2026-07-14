from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import logging

import pytest
from fastapi import Response

import app.api.crawl_jobs as crawl_jobs_api
from app.api.crawl_jobs import _build_crawl_request_created_log_message
from app.schemas.crawl_job import CrawlJobCreateRequest


def test_build_crawl_request_created_log_message_includes_request_and_batch_context():
    message = _build_crawl_request_created_log_message(
        request_id="req-1",
        source_site="jobsdb",
        crawl_job_id="crawl-1",
        crawl_phase="detail",
        crawl_mode="headed",
        max_pages=3,
        category_count=1,
        source_listing_crawl_job_id="listing-batch-9",
    )

    assert message == (
        "SCRAPE_REQUEST_CREATED request_id=req-1 source=jobsdb crawl_job_id=crawl-1 "
        "phase=detail mode=headed max_pages=3 categories=1 "
        "source_listing_crawl_job_id=listing-batch-9"
    )


@pytest.mark.asyncio
async def test_list_crawl_tasks_batch_loads_detail_progress_events(monkeypatch):
    observed_event_types = set()
    fake_job = SimpleNamespace(id="job-1")

    class _FakeRepository:
        def list_crawl_task_page(self, db, **filters):
            return [fake_job], 1

        def list_latest_events_for_jobs(self, db, *, crawl_job_ids):
            return {}

        def list_events_by_job_ids(self, db, *, crawl_job_ids, event_types):
            observed_event_types.update(event_types)
            return {}

    monkeypatch.setattr(crawl_jobs_api, "crawl_job_repository", _FakeRepository())
    monkeypatch.setattr(
        crawl_jobs_api,
        "build_crawl_task_snapshot",
        lambda *args, **kwargs: {
            "crawl_job_id": "job-1",
            "persisted_status": "running",
            "status": "running",
            "source_site": "offertoday",
        },
    )

    payload = await crawl_jobs_api.list_crawl_tasks(
        page=1,
        page_size=10,
        status=None,
        source_site="offertoday",
        crawl_mode=None,
        time_range="all",
        db=object(),
    )

    assert payload.total == 1
    assert {
        "crawl.detail_attempt",
        "crawl.detail_cohort_frozen",
        "crawl.detail_reconciled",
    }.issubset(observed_event_types)


@pytest.mark.asyncio
async def test_create_crawl_job_accepts_positional_direct_call_db_argument(monkeypatch):
    supplied_db = object()
    captured: dict[str, object] = {}
    crawl_job_id = uuid4()

    class _FakeDispatchService:
        def dispatch_manual_crawl_job(self, db, **kwargs):
            captured["db"] = db
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    request_payload={},
                )
            )

    monkeypatch.setattr(crawl_jobs_api, "dispatch_service", _FakeDispatchService())

    request = CrawlJobCreateRequest(
        source_site="jobsdb",
        crawl_phase="detail",
        source_listing_crawl_job_id=uuid4(),
    )

    await crawl_jobs_api.create_crawl_job(
        request,
        Response(),
        supplied_db,
    )

    assert captured["db"] is supplied_db


@pytest.mark.asyncio
async def test_create_crawl_job_schedule_log_uses_dispatched_request_payload(monkeypatch, caplog):
    supplied_db = object()
    schedule_id = uuid4()
    crawl_job_id = uuid4()
    schedule = SimpleNamespace(
        id=schedule_id,
        source_site="jobsdb",
        crawl_phase=None,
        crawl_mode=None,
        max_pages=None,
        category_ids=["cat-1"],
    )

    class _FakeDispatchService:
        def dispatch_schedule_crawl_job(self, db, **kwargs):
            assert db is supplied_db
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    request_payload={
                        "crawl_phase": "detail",
                        "crawl_mode": "headed",
                        "max_pages": 99,
                        "category_ids": ["cat-1", "cat-2"],
                        "source_listing_crawl_job_id": "listing-batch-9",
                    },
                )
            )

    async def fake_validate_effective_category_ids(source_site, category_ids):
        return None

    monkeypatch.setattr(
        crawl_jobs_api.schedule_repository,
        "get_schedule_by_id",
        lambda db, schedule_id_value: schedule,
    )
    monkeypatch.setattr(crawl_jobs_api, "dispatch_service", _FakeDispatchService())
    monkeypatch.setattr(crawl_jobs_api, "_validate_effective_category_ids", fake_validate_effective_category_ids)

    request = CrawlJobCreateRequest(schedule_id=schedule_id)
    request_context = SimpleNamespace(state=SimpleNamespace(request_id="req-4"))

    with caplog.at_level(logging.INFO, logger="app.api.crawl_jobs"):
        await crawl_jobs_api.create_crawl_job(
            request=request,
            response=Response(),
            db=supplied_db,
            request_context=request_context,
        )

    assert (
        "SCRAPE_REQUEST_CREATED request_id=req-4 source=jobsdb "
        f"crawl_job_id={crawl_job_id} trigger=schedule schedule_id={schedule_id} "
        "phase=detail mode=headed max_pages=99 categories=2 "
        "source_listing_crawl_job_id=listing-batch-9"
    ) in caplog.text
