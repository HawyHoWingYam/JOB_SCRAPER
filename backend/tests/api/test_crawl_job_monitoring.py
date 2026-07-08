from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

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
