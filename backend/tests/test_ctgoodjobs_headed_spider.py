from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl):
    import crawler.job_crawler.spiders.ctgoodjobs_headed_spider as spider_module
    from app.scraper.ctgoodjobs.html_fetcher import CTGoodJobsFetchError

    category = SimpleNamespace(
        source_classification_id="ctgoodjobs:021",
        slug="information-technology",
        name="Information Technology",
        url="https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
    )

    class FakeBrowserPageScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_page_html(self, url: str, *, stage: str, referer: str | None = None):
            return await fetch_impl(url=url, stage=stage, referer=referer)

    monkeypatch.setattr(
        spider_module,
        "CTGoodJobsBrowserPageScraper",
        lambda *args, **kwargs: FakeBrowserPageScraper(),
    )
    monkeypatch.setattr(spider_module, "parse_category_registry", lambda html: [category])
    return spider_module, category, CTGoodJobsFetchError


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_fetches_registry_category_and_detail_via_browser(monkeypatch):
    seen_calls: list[tuple[str, str, str | None]] = []

    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        seen_calls.append((stage, url, referer))
        return f"<html>{stage}</html>"

    spider_module, category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: {
            "job_ids": ["10108385"],
            "job_urls": ["https://jobs.ctgoodjobs.hk/job/10108385"],
        },
    )
    monkeypatch.setattr(
        spider_module,
        "parse_detail_page",
        lambda *args, **kwargs: {"job_id": "ctgoodjobs:10108385", "category": category.name},
    )
    monkeypatch.setattr(
        spider_module,
        "build_canonical_job",
        lambda parsed_job: SimpleNamespace(to_dict=lambda: dict(parsed_job)),
    )

    emitted_progress = []
    emitted_items = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-1",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_mode": "headed"},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=emitted_items.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 1, "detail_pages_skipped": 0}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_items == [{"job_id": "ctgoodjobs:10108385", "category": "Information Technology"}]
    assert seen_calls == [
        ("registry", "https://jobs.ctgoodjobs.hk/jobs", None),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology", "https://jobs.ctgoodjobs.hk/jobs"),
        ("detail_page", "https://jobs.ctgoodjobs.hk/job/10108385", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology"),
    ]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_skips_detail_pages_after_browser_retry_exhaustion(monkeypatch):
    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        if url.endswith("/10108385"):
            raise fetch_error_type(
                stage=stage,
                url=url,
                attempts=3,
                exception_type="RuntimeError",
            )
        return f"<html>{stage}</html>"

    spider_module, category, fetch_error_type = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: {
            "job_ids": ["10108385", "10108386"],
            "job_urls": [
                "https://jobs.ctgoodjobs.hk/job/10108385",
                "https://jobs.ctgoodjobs.hk/job/10108386",
            ],
        },
    )
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

    emitted_items = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-2",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_mode": "headed"},
        emit_page_processed=lambda payload: None,
        emit_item_emitted=emitted_items.append,
    )

    assert result["items_emitted"] == 1
    assert result["detail_pages_skipped"] == 1
    assert emitted_items == [{"job_id": "ctgoodjobs:10108386", "category": "Information Technology"}]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_raises_when_registry_browser_fetch_fails(monkeypatch):
    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        raise fetch_error_type(
            stage=stage,
            url=url,
            attempts=3,
            exception_type="RuntimeError",
        )

    spider_module, _category, fetch_error_type = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)

    with pytest.raises(Exception, match=r"registry.*RuntimeError.*https://jobs\.ctgoodjobs\.hk/jobs"):
        await spider_module.CTGoodJobsHeadedSpider().crawl(
            crawl_job_id="headed-ct-3",
            request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_mode": "headed"},
            emit_page_processed=lambda payload: None,
            emit_item_emitted=lambda item: None,
        )
