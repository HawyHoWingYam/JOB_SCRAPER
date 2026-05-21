from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.sources.ctgoodjobs import parsers
from app.utils import anti_detection


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ctgoodjobs"


def test_ctgoodjobs_spider_builds_canonical_item_from_parsed_detail():
    from crawler.job_crawler.spiders.ctgoodjobs_spider import build_canonical_job

    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    parsed = parsers.parse_detail_page(
        html,
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Data Jobs",
        source_classification_slug="data-jobs",
        url="https://jobs.ctgoodjobs.hk/job/10090657",
    )
    item = build_canonical_job(parsed)

    assert item.source_site == "ctgoodjobs"
    assert item.source_job_id == "10090657"
    assert item.source_url == "https://jobs.ctgoodjobs.hk/job/10090657"
    assert item.title == "Lead Data Analyst | CTgoodjobs"


class _StubAsyncClient:
    def __init__(self, responses_by_url: dict[str, list[tuple[int, str] | Exception]]):
        self._responses_by_url = {
            url: list(responses)
            for url, responses in responses_by_url.items()
        }
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aclose(self) -> None:
        return None

    async def get(self, url: str, headers=None):
        self.calls.append({"url": url, "headers": headers})
        queue = self._responses_by_url.get(url)
        if not queue:
            raise AssertionError(f"Unexpected GET: {url}")

        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response

        status_code, body = response
        request = httpx.Request("GET", url, headers=headers)
        return httpx.Response(status_code, text=body, request=request)


def _patch_ctgoodjobs_spider(monkeypatch, stub_client: _StubAsyncClient):
    import crawler.job_crawler.spiders.ctgoodjobs_spider as spider_module

    async def _no_wait(self, attempt: int) -> None:
        return None

    category = SimpleNamespace(
        source_classification_id="ctgoodjobs:021",
        slug="information-technology",
        name="Information Technology",
        url="https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
    )

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", _no_wait)
    monkeypatch.setattr(spider_module.httpx, "AsyncClient", lambda *args, **kwargs: stub_client)
    monkeypatch.setattr(spider_module, "parse_category_registry", lambda html: [category])
    return spider_module, category


@pytest.mark.asyncio
async def test_ctgoodjobs_spider_listing_phase_retries_registry_fetch_and_emits_staging_rows(monkeypatch):
    registry_url = "https://jobs.ctgoodjobs.hk/jobs"
    category_url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    detail_url = "https://jobs.ctgoodjobs.hk/job/1001"
    stub_client = _StubAsyncClient(
        {
            registry_url: [(504, "gateway timeout"), (200, "registry ok")],
            category_url: [(200, "category ok")],
            detail_url: [(200, "detail ok")],
        }
    )
    spider_module, category = _patch_ctgoodjobs_spider(monkeypatch, stub_client)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: {"job_ids": ["1001"], "job_urls": [detail_url]},
    )
    monkeypatch.setattr(
        spider_module,
        "parse_detail_page",
        lambda *args, **kwargs: {"job_id": "ctgoodjobs:1001", "category": category.name},
    )
    monkeypatch.setattr(
        spider_module,
        "build_canonical_job",
        lambda parsed_job: SimpleNamespace(to_dict=lambda: dict(parsed_job)),
    )

    page_events: list[dict] = []
    listings: list[dict] = []
    result = await spider_module.CTGoodJobsSpider().crawl(
        crawl_job_id="crawl-1",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_phase": "listing"},
        emit_page_processed=page_events.append,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=listings.append,
    )

    assert result["pages_processed"] == 1
    assert result["items_emitted"] == 0
    assert page_events[0]["job_ids_collected"] == 1
    assert listings == [
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "1001",
            "source_url": detail_url,
            "source_classification_id": "ctgoodjobs:021",
            "source_classification_name": "Information Technology",
            "listing_page": 1,
            "listing_rank": 1,
            "listing_payload": {
                "job_id": "1001",
                "job_url": detail_url,
                "category_slug": "information-technology",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
            },
        }
    ]
    assert sum(1 for call in stub_client.calls if call["url"] == registry_url) == 2


@pytest.mark.asyncio
async def test_ctgoodjobs_spider_detail_phase_retries_detail_fetch_and_emits_item(monkeypatch):
    registry_url = "https://jobs.ctgoodjobs.hk/jobs"
    category_url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    detail_url = "https://jobs.ctgoodjobs.hk/job/1001"
    stub_client = _StubAsyncClient(
        {
            registry_url: [(200, "registry ok")],
            category_url: [(200, "category ok")],
            detail_url: [(504, "gateway timeout"), (200, "detail ok")],
        }
    )
    spider_module, category = _patch_ctgoodjobs_spider(monkeypatch, stub_client)
    monkeypatch.setattr(
        spider_module,
        "parse_detail_page",
        lambda *args, **kwargs: {"job_id": "ctgoodjobs:1001", "category": category.name},
    )
    monkeypatch.setattr(
        spider_module,
        "build_canonical_job",
        lambda parsed_job: SimpleNamespace(to_dict=lambda: dict(parsed_job)),
    )

    items: list[dict] = []
    result = await spider_module.CTGoodJobsSpider().crawl(
        crawl_job_id="crawl-2",
        request_payload={
            "crawl_phase": "detail",
            "detail_targets": [
                {
                    "listing_id": "listing-1",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "1001",
                    "source_url": detail_url,
                    "source_classification_id": "ctgoodjobs:021",
                    "listing_payload": {"job_id": "1001"},
                }
            ],
        },
        emit_page_processed=lambda payload: None,
        emit_item_emitted=items.append,
    )

    assert result["items_emitted"] == 1
    assert items == [
        {
            "listing_id": "listing-1",
            "source_listing_crawl_job_id": "listing-crawl-1",
            "job": {"job_id": "ctgoodjobs:1001", "category": "Information Technology"},
        }
    ]
    assert sum(1 for call in stub_client.calls if call["url"] == detail_url) == 2


@pytest.mark.asyncio
async def test_ctgoodjobs_spider_detail_phase_marks_retry_exhaustion_as_skipped(monkeypatch):
    registry_url = "https://jobs.ctgoodjobs.hk/jobs"
    category_url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    detail_url_1 = "https://jobs.ctgoodjobs.hk/job/1001"
    detail_url_2 = "https://jobs.ctgoodjobs.hk/job/1002"
    stub_client = _StubAsyncClient(
        {
            registry_url: [(200, "registry ok")],
            category_url: [(200, "category ok")],
            detail_url_1: [(504, "gateway timeout"), (504, "gateway timeout"), (504, "gateway timeout")],
            detail_url_2: [(200, "detail ok")],
        }
    )
    spider_module, category = _patch_ctgoodjobs_spider(monkeypatch, stub_client)
    monkeypatch.setattr(
        spider_module,
        "parse_detail_page",
        lambda *args, **kwargs: {
            "job_id": f"ctgoodjobs:{kwargs['url'].rsplit('/', 1)[-1]}",
            "category": category.name,
        },
    )
    monkeypatch.setattr(
        spider_module,
        "build_canonical_job",
        lambda parsed_job: SimpleNamespace(to_dict=lambda: dict(parsed_job)),
    )

    items: list[dict] = []
    failed_targets: list[tuple[dict, str]] = []
    result = await spider_module.CTGoodJobsSpider().crawl(
        crawl_job_id="crawl-3",
        request_payload={
            "crawl_phase": "detail",
            "detail_targets": [
                {
                    "listing_id": "listing-1",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "1001",
                    "source_url": detail_url_1,
                    "source_classification_id": "ctgoodjobs:021",
                    "listing_payload": {"job_id": "1001"},
                },
                {
                    "listing_id": "listing-2",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "1002",
                    "source_url": detail_url_2,
                    "source_classification_id": "ctgoodjobs:021",
                    "listing_payload": {"job_id": "1002"},
                },
            ],
        },
        emit_page_processed=lambda payload: None,
        emit_item_emitted=items.append,
        mark_detail_failed=lambda target, error: failed_targets.append((target, error)),
    )

    assert result["items_emitted"] == 1
    assert result["detail_pages_skipped"] == 1
    assert items == [
        {
            "listing_id": "listing-2",
            "source_listing_crawl_job_id": "listing-crawl-1",
            "job": {"job_id": "ctgoodjobs:1002", "category": "Information Technology"},
        }
    ]
    assert failed_targets[0][0]["listing_id"] == "listing-1"
    assert sum(1 for call in stub_client.calls if call["url"] == detail_url_1) == 3


@pytest.mark.asyncio
async def test_ctgoodjobs_spider_raises_when_registry_fetch_exhausts_retries(monkeypatch):
    registry_url = "https://jobs.ctgoodjobs.hk/jobs"
    category_url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    stub_client = _StubAsyncClient(
        {
            registry_url: [(504, "gateway timeout"), (504, "gateway timeout"), (504, "gateway timeout")],
            category_url: [(200, "category ok")],
        }
    )
    spider_module, _category = _patch_ctgoodjobs_spider(monkeypatch, stub_client)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: {"job_ids": ["1001"], "job_urls": ["https://jobs.ctgoodjobs.hk/job/1001"]},
    )

    emitted_listings = []
    result = await spider_module.CTGoodJobsSpider().crawl(
        crawl_job_id="crawl-4",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_phase": "listing"},
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda item: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result["pages_processed"] == 1
    assert emitted_listings[0]["source_classification_id"] == "ctgoodjobs:021"
    assert sum(1 for call in stub_client.calls if call["url"] == registry_url) == 3


@pytest.mark.asyncio
async def test_ctgoodjobs_spider_listing_phase_fetches_oldest_pages_first(monkeypatch):
    registry_url = "https://jobs.ctgoodjobs.hk/jobs"
    category_url = "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"
    page_2_url = f"{category_url}?page=2"
    detail_url_1 = "https://jobs.ctgoodjobs.hk/job/1001"
    detail_url_2 = "https://jobs.ctgoodjobs.hk/job/1002"
    stub_client = _StubAsyncClient(
        {
            registry_url: [(200, "registry ok")],
            category_url: [(200, "category page 1")],
            page_2_url: [(200, "category page 2")],
            detail_url_1: [(200, "detail 1")],
            detail_url_2: [(200, "detail 2")],
        }
    )
    spider_module, category = _patch_ctgoodjobs_spider(monkeypatch, stub_client)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: (
            {"job_ids": ["1001"], "job_urls": [detail_url_1]}
            if kwargs["page"] == 1
            else {
                "job_ids": ["1001", "1002"],
                "job_urls": [detail_url_1, detail_url_2],
            }
        ),
    )
    emitted_listings = []
    result = await spider_module.CTGoodJobsSpider().crawl(
        crawl_job_id="crawl-5",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 2, "crawl_phase": "listing"},
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result["pages_processed"] == 2
    assert result["items_emitted"] == 0
    assert [call["url"] for call in stub_client.calls] == [
        registry_url,
        page_2_url,
        category_url,
    ]
    assert emitted_listings == [
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "1001",
            "source_url": detail_url_1,
            "source_classification_id": "ctgoodjobs:021",
            "source_classification_name": "Information Technology",
            "listing_page": 2,
            "listing_rank": 1,
            "listing_payload": {
                "job_id": "1001",
                "job_url": detail_url_1,
                "category_slug": "information-technology",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
            },
        },
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "1002",
            "source_url": detail_url_2,
            "source_classification_id": "ctgoodjobs:021",
            "source_classification_name": "Information Technology",
            "listing_page": 2,
            "listing_rank": 2,
            "listing_payload": {
                "job_id": "1002",
                "job_url": detail_url_2,
                "category_slug": "information-technology",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
            },
        },
    ]
