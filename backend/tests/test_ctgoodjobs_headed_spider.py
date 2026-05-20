from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.manual_action import ManualActionRequiredError


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
async def test_ctgoodjobs_headed_spider_listing_phase_fetches_registry_and_category_via_browser(monkeypatch):
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
    emitted_listings = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-1",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_mode": "headed", "crawl_phase": "listing"},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 0, "detail_pages_skipped": 0}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_listings[0]["source_job_id"] == "10108385"
    assert seen_calls == [
        ("registry", "https://jobs.ctgoodjobs.hk/jobs", None),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology", "https://jobs.ctgoodjobs.hk/jobs"),
    ]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_detail_phase_skips_failed_pages(monkeypatch):
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
    failed_targets = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-2",
        request_payload={
            "crawl_phase": "detail",
            "crawl_mode": "headed",
            "detail_targets": [
                {
                    "listing_id": "listing-1",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "10108385",
                    "source_url": "https://jobs.ctgoodjobs.hk/job/10108385",
                    "source_classification_id": "ctgoodjobs:021",
                    "listing_payload": {"job_id": "10108385"},
                },
                {
                    "listing_id": "listing-2",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "10108386",
                    "source_url": "https://jobs.ctgoodjobs.hk/job/10108386",
                    "source_classification_id": "ctgoodjobs:021",
                    "listing_payload": {"job_id": "10108386"},
                },
            ],
        },
        emit_page_processed=lambda payload: None,
        emit_item_emitted=emitted_items.append,
        mark_detail_failed=lambda target, error: failed_targets.append((target, error)),
    )

    assert result["items_emitted"] == 1
    assert result["detail_pages_skipped"] == 1
    assert emitted_items == [
        {
            "listing_id": "listing-2",
            "source_listing_crawl_job_id": "listing-crawl-1",
            "job": {"job_id": "ctgoodjobs:10108386", "category": "Information Technology"},
        }
    ]
    assert failed_targets[0][0]["listing_id"] == "listing-1"


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
            request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 1, "crawl_mode": "headed", "crawl_phase": "listing"},
            emit_page_processed=lambda payload: None,
            emit_item_emitted=lambda item: None,
        )


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_listing_phase_fetches_oldest_pages_first(monkeypatch):
    seen_calls: list[tuple[str, str, str | None]] = []

    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        seen_calls.append((stage, url, referer))
        return f"<html>{stage}</html>"

    spider_module, category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: (
            {
                "job_ids": ["10108385"],
                "job_urls": ["https://jobs.ctgoodjobs.hk/job/10108385"],
            }
            if kwargs["page"] == 1
            else {
                "job_ids": ["10108385", "10108386"],
                "job_urls": [
                    "https://jobs.ctgoodjobs.hk/job/10108385",
                    "https://jobs.ctgoodjobs.hk/job/10108386",
                ],
            }
        ),
    )
    emitted_listings = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-4",
        request_payload={"category_ids": ["ctgoodjobs:021"], "max_pages": 2, "crawl_mode": "headed", "crawl_phase": "listing"},
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 2, "items_emitted": 0, "detail_pages_skipped": 0}
    assert seen_calls == [
        ("registry", "https://jobs.ctgoodjobs.hk/jobs", None),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=2", "https://jobs.ctgoodjobs.hk/jobs"),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology", "https://jobs.ctgoodjobs.hk/jobs"),
    ]
    assert emitted_listings == [
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "10108385",
            "source_url": "https://jobs.ctgoodjobs.hk/job/10108385",
            "source_classification_id": "ctgoodjobs:021",
            "source_classification_name": "Information Technology",
            "listing_page": 2,
            "listing_rank": 1,
            "listing_payload": {
                "job_id": "10108385",
                "job_url": "https://jobs.ctgoodjobs.hk/job/10108385",
                "category_slug": "information-technology",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
            },
        },
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "10108386",
            "source_url": "https://jobs.ctgoodjobs.hk/job/10108386",
            "source_classification_id": "ctgoodjobs:021",
            "source_classification_name": "Information Technology",
            "listing_page": 2,
            "listing_rank": 2,
            "listing_payload": {
                "job_id": "10108386",
                "job_url": "https://jobs.ctgoodjobs.hk/job/10108386",
                "category_slug": "information-technology",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
            },
        },
    ]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_listing_manual_action_error_includes_resume_context(monkeypatch):
    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        if stage == "category_page" and "?page=2" not in url:
            raise ManualActionRequiredError(
                source_site="ctgoodjobs",
                stage=stage,
                blocked_url=url,
                referer=referer,
                message="captcha encountered",
            )
        return f"<html>{stage}</html>"

    spider_module, category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
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

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await spider_module.CTGoodJobsHeadedSpider().crawl(
            crawl_job_id="headed-ct-5",
            request_payload={
                "category_ids": ["ctgoodjobs:021"],
                "max_pages": 2,
                "crawl_mode": "headed",
                "crawl_phase": "listing",
            },
            emit_page_processed=lambda payload: None,
            emit_item_emitted=lambda payload: None,
            emit_listing_emitted=lambda payload: None,
        )

    assert exc_info.value.resume_context["crawl_phase"] == "listing"
    assert exc_info.value.resume_context["category_id"] == category.source_classification_id
    assert exc_info.value.resume_context["page"] == 1
    assert exc_info.value.resume_context["page_direction"] == "descending"
    assert exc_info.value.resume_context["seen_job_ids"] == ["10108385", "10108386"]
    assert exc_info.value.resume_context["listing_rank"] == 2


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_listing_resume_prefers_category_id_over_misleading_category_index(monkeypatch):
    seen_calls: list[tuple[str, str, str | None]] = []

    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        seen_calls.append((stage, url, referer))
        return f"<html>{stage}</html>"

    spider_module, _category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
    first_category = SimpleNamespace(
        source_classification_id="ctgoodjobs:001",
        slug="banking-finance",
        name="Banking & Finance",
        url="https://jobs.ctgoodjobs.hk/jobs/jobs-in-banking-finance",
    )
    second_category = SimpleNamespace(
        source_classification_id="ctgoodjobs:021",
        slug="information-technology",
        name="Information Technology",
        url="https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
    )
    monkeypatch.setattr(spider_module, "parse_category_registry", lambda html: [first_category, second_category])
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: {
            "job_ids": [f"{kwargs['source_classification_id']}-{kwargs['page']}"],
            "job_urls": [f"{kwargs['url']}/detail"],
        },
    )

    emitted_listings = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-6",
        request_payload={
            "category_ids": ["ctgoodjobs:001", "ctgoodjobs:021"],
            "max_pages": 2,
            "crawl_mode": "headed",
            "crawl_phase": "listing",
            "is_resume": True,
            "resume_context": {
                "crawl_phase": "listing",
                "category_id": "ctgoodjobs:021",
                "category_index": 0,
                "page": 2,
            },
        },
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 2, "items_emitted": 0, "detail_pages_skipped": 0}
    assert seen_calls == [
        ("registry", "https://jobs.ctgoodjobs.hk/jobs", None),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=2", "https://jobs.ctgoodjobs.hk/jobs"),
        ("category_page", "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology", "https://jobs.ctgoodjobs.hk/jobs"),
    ]
    assert [payload["source_classification_id"] for payload in emitted_listings] == ["ctgoodjobs:021", "ctgoodjobs:021"]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_listing_resume_seeds_seen_job_ids_and_listing_rank(monkeypatch):
    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        return f"<html>{stage}</html>"

    spider_module, category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)
    monkeypatch.setattr(
        spider_module,
        "parse_category_page",
        lambda *args, **kwargs: (
            {
                "job_ids": ["10108385", "10108386"],
                "job_urls": [
                    "https://jobs.ctgoodjobs.hk/job/10108385",
                    "https://jobs.ctgoodjobs.hk/job/10108386",
                ],
            }
            if kwargs["page"] == 2
            else {
                "job_ids": ["10108387"],
                "job_urls": ["https://jobs.ctgoodjobs.hk/job/10108387"],
            }
        ),
    )

    emitted_listings = []
    result = await spider_module.CTGoodJobsHeadedSpider().crawl(
        crawl_job_id="headed-ct-7",
        request_payload={
            "category_ids": [category.source_classification_id],
            "max_pages": 2,
            "crawl_mode": "headed",
            "crawl_phase": "listing",
            "is_resume": True,
            "resume_context": {
                "crawl_phase": "listing",
                "category_id": category.source_classification_id,
                "category_index": 0,
                "page": 2,
                "seen_job_ids": ["10108385"],
                "listing_rank": 1,
            },
        },
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 2, "items_emitted": 0, "detail_pages_skipped": 0}
    assert emitted_listings == [
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "10108386",
            "source_url": "https://jobs.ctgoodjobs.hk/job/10108386",
            "source_classification_id": category.source_classification_id,
            "source_classification_name": category.name,
            "listing_page": 2,
            "listing_rank": 2,
            "listing_payload": {
                "job_id": "10108386",
                "job_url": "https://jobs.ctgoodjobs.hk/job/10108386",
                "category_slug": category.slug,
                "source_classification_id": category.source_classification_id,
                "source_classification_name": category.name,
            },
        },
        {
            "source_site": "ctgoodjobs",
            "source_job_id": "10108387",
            "source_url": "https://jobs.ctgoodjobs.hk/job/10108387",
            "source_classification_id": category.source_classification_id,
            "source_classification_name": category.name,
            "listing_page": 1,
            "listing_rank": 3,
            "listing_payload": {
                "job_id": "10108387",
                "job_url": "https://jobs.ctgoodjobs.hk/job/10108387",
                "category_slug": category.slug,
                "source_classification_id": category.source_classification_id,
                "source_classification_name": category.name,
            },
        },
    ]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_detail_manual_action_error_includes_resume_context(monkeypatch):
    async def fetch_impl(*, url: str, stage: str, referer: str | None = None):
        if stage == "detail_page":
            raise ManualActionRequiredError(
                source_site="ctgoodjobs",
                stage=stage,
                blocked_url=url,
                referer=referer,
                message="verification required",
            )
        return f"<html>{stage}</html>"

    spider_module, _category, _ = _patch_ctgoodjobs_headed_spider(monkeypatch, fetch_impl)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await spider_module.CTGoodJobsHeadedSpider().crawl(
            crawl_job_id="headed-ct-8",
            request_payload={
                "crawl_phase": "detail",
                "crawl_mode": "headed",
                "detail_targets": [
                    {
                        "listing_id": "listing-1",
                        "source_listing_crawl_job_id": "listing-crawl-1",
                        "source_job_id": "10108385",
                        "source_url": "https://jobs.ctgoodjobs.hk/job/10108385",
                        "source_classification_id": "ctgoodjobs:021",
                        "listing_payload": {"job_id": "10108385"},
                    }
                ],
            },
            emit_page_processed=lambda payload: None,
            emit_item_emitted=lambda payload: None,
        )

    assert exc_info.value.resume_context["crawl_phase"] == "detail"
    assert exc_info.value.resume_context["listing_id"] == "listing-1"
    assert exc_info.value.resume_context["source_listing_crawl_job_id"] == "listing-crawl-1"
    assert exc_info.value.resume_context["source_job_id"] == "10108385"
