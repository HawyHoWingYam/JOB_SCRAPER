from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.scraper.category_scraper import (
    CategoryListScraper,
    JobsDBListingPaginationInconsistentError,
)
from scripts import jobsdb_standalone_crawl as jobsdb_crawl


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_jobsdb_listing_retries_transient_server_disconnect() -> None:
    attempts: list[httpx.Request] = []
    retry_delays: list[float] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.",
                request=request,
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/json"},
            json={"totalCount": 1, "data": [{"id": "job-1"}]},
        )

    async def record_sleep(seconds: float) -> None:
        retry_delays.append(seconds)

    scraper = CategoryListScraper(sleep=record_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as client:
        result = await scraper.fetch_page(6281, page=7, client=client)

    assert result["data"] == [{"id": "job-1"}]
    assert len(attempts) == 2
    assert attempts[0].url == attempts[1].url
    assert retry_delays == [1.0]


@pytest.mark.asyncio
async def test_jobsdb_listing_logs_only_retryable_transport_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("sensitive upstream detail", request=request)
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/json"},
            json={"totalCount": 0, "data": []},
        )

    scraper = CategoryListScraper(sleep=_no_sleep)
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle_request)
        ) as client:
            await scraper.fetch_page(6281, page=7, client=client)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "SCRAPE_LISTING_PAGE_RETRY" in message
    assert "error_type=RemoteProtocolError" in message
    assert "attempt=1" in message
    assert "max_attempts=4" in message
    assert "sensitive upstream detail" not in message


@pytest.mark.asyncio
async def test_jobsdb_listing_stops_after_bounded_transport_retries() -> None:
    attempts = 0
    retry_delays: list[float] = []

    def disconnect(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.",
            request=request,
        )

    async def record_sleep(seconds: float) -> None:
        retry_delays.append(seconds)

    scraper = CategoryListScraper(sleep=record_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as client:
        with pytest.raises(
            httpx.RemoteProtocolError,
            match="Server disconnected without sending a response",
        ):
            await scraper.fetch_page(6281, page=7, client=client)

    assert attempts == 4
    assert retry_delays == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_jobsdb_listing_does_not_retry_http_status_failures() -> None:
    attempts = 0
    retry_delays: list[float] = []

    def service_unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            request=request,
            headers={"content-type": "application/json"},
            json={"error": "unavailable"},
        )

    async def record_sleep(seconds: float) -> None:
        retry_delays.append(seconds)

    scraper = CategoryListScraper(sleep=record_sleep)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(service_unavailable)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await scraper.fetch_page(6281, page=7, client=client)

    assert attempts == 1
    assert retry_delays == []


@pytest.mark.asyncio
async def test_jobsdb_listing_does_not_retry_local_protocol_errors() -> None:
    attempts = 0
    retry_delays: list[float] = []

    def invalid_request(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.LocalProtocolError("invalid request", request=request)

    async def record_sleep(seconds: float) -> None:
        retry_delays.append(seconds)

    scraper = CategoryListScraper(sleep=record_sleep)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(invalid_request)
    ) as client:
        with pytest.raises(httpx.LocalProtocolError):
            await scraper.fetch_page(6281, page=7, client=client)

    assert attempts == 1
    assert retry_delays == []


@pytest.mark.asyncio
async def test_jobsdb_listing_retry_backoff_is_cancellation_aware() -> None:
    attempts = 0

    def disconnect(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError("disconnected", request=request)

    async def cancel_during_backoff(_seconds: float) -> None:
        raise asyncio.CancelledError

    scraper = CategoryListScraper(sleep=cancel_during_backoff)
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as client:
        with pytest.raises(asyncio.CancelledError):
            await scraper.fetch_page(6281, page=7, client=client)

    assert attempts == 1


@pytest.mark.asyncio
async def test_jobsdb_empty_drifted_tail_still_processes_cached_first_page() -> None:
    class Scraper(CategoryListScraper):
        def __init__(self) -> None:
            super().__init__(sleep=_no_sleep)
            self.requested_pages: list[int] = []

        async def fetch_page(self, _classification_id, page=1, client=None):
            self.requested_pages.append(page)
            if page == 1:
                return {
                    "totalCount": 3_914,
                    "data": [{"id": "page-1-job"}],
                }
            return {"totalCount": 3_791, "data": []}

    scraper = Scraper()
    scraper.reuse_first_page = True
    staged_pages: list[tuple[int, tuple[str, ...]]] = []

    async def stage_page(*, page, jobs, **_kwargs) -> None:
        staged_pages.append((page, tuple(str(job["id"]) for job in jobs)))

    result = await scraper.scrape_category(
        6281,
        max_pages=200,
        page_sink=stage_page,
    )

    assert scraper.requested_pages == [1, 123, 122]
    assert staged_pages == [
        (123, ()),
        (122, ()),
        (1, ("page-1-job",)),
    ]
    assert result["job_ids"] == ["page-1-job"]
    assert result["pages_scraped"] == 3


@pytest.mark.asyncio
async def test_jobsdb_advertised_nonempty_scope_with_no_identities_fails() -> None:
    class Scraper(CategoryListScraper):
        def __init__(self) -> None:
            super().__init__(sleep=_no_sleep)

        async def fetch_page(self, _classification_id, page=1, client=None):
            return {"totalCount": 64, "data": []}

    scraper = Scraper()
    scraper.reuse_first_page = True

    with pytest.raises(
        JobsDBListingPaginationInconsistentError,
        match=(
            "JobsDB listing pagination inconsistent: "
            "total_count=64 total_pages=2 pages_scraped=2"
        ),
    ):
        await scraper.scrape_category(6281, max_pages=2)


@pytest.mark.asyncio
async def test_jobsdb_authoritative_empty_scope_remains_successful() -> None:
    class Scraper(CategoryListScraper):
        def __init__(self) -> None:
            super().__init__(sleep=_no_sleep)
            self.requested_pages: list[int] = []

        async def fetch_page(self, _classification_id, page=1, client=None):
            self.requested_pages.append(page)
            return {"totalCount": 0, "data": []}

    scraper = Scraper()
    scraper.reuse_first_page = True
    staged_pages: list[int] = []

    async def stage_page(*, page, **_kwargs) -> None:
        staged_pages.append(page)

    result = await scraper.scrape_category(
        6281,
        max_pages=200,
        page_sink=stage_page,
    )

    assert scraper.requested_pages == [1]
    assert staged_pages == []
    assert result["job_ids"] == []
    assert result["pages_scraped"] == 0


@pytest.mark.asyncio
async def test_jobsdb_executor_records_pagination_inconsistency_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawl_job_id = "57324f0b-7564-43f0-a2b1-029e07434e01"
    runtime = SimpleNamespace(
        started=[],
        completed=[],
        failed=[],
        mark_started=lambda **kwargs: runtime.started.append(kwargs),
        mark_completed=lambda **kwargs: runtime.completed.append(kwargs),
        mark_failed=lambda **kwargs: runtime.failed.append(kwargs),
    )
    startup = SimpleNamespace(
        source_site="jobsdb",
        request_payload={
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headless",
            "category_ids": ["jobsdb:6281"],
            "max_pages": 200,
        },
        listing_runtime_plan=None,
        detail_runtime_plan=None,
    )

    class CancellationToken:
        def __init__(self, **_kwargs) -> None:
            return None

        def raise_if_cancelled(self) -> None:
            return None

    async def fail_listing(*_args, **_kwargs):
        raise JobsDBListingPaginationInconsistentError(
            total_count=3_914,
            total_pages=123,
            pages_scraped=3,
        )

    monkeypatch.setattr(
        jobsdb_crawl,
        "_load_runtime_input",
        lambda *_args, **_kwargs: startup,
    )
    monkeypatch.setattr(jobsdb_crawl, "CrawlCancellationToken", CancellationToken)
    monkeypatch.setattr(jobsdb_crawl, "CrawlJobRuntime", lambda: runtime)
    monkeypatch.setattr(jobsdb_crawl, "run_listing_phase", fail_listing)

    exit_code = await jobsdb_crawl.main(["--crawl-job-id", crawl_job_id])

    assert exit_code == 1
    assert len(runtime.started) == 1
    assert runtime.completed == []
    assert len(runtime.failed) == 1
    assert runtime.failed[0]["crawl_job_id"] == crawl_job_id
    assert runtime.failed[0]["error_message"] == (
        "JobsDB listing pagination inconsistent: "
        "total_count=3914 total_pages=123 pages_scraped=3"
    )
