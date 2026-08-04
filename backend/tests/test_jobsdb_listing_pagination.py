from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper.category_scraper import (
    CategoryListScraper,
    JobsDBListingPaginationInconsistentError,
)
from scripts import jobsdb_standalone_crawl as jobsdb_crawl


async def _no_sleep(_seconds: float) -> None:
    return None


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
