import json
import sys
from pathlib import Path
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


@pytest.mark.asyncio
async def test_jobsdb_headed_spider_listing_phase_emits_staging_rows(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_headed_spider import JobsDBHeadedSpider

    payload = json.loads((FIXTURES / "search_response.json").read_text(encoding="utf-8"))
    emitted_listings = []
    emitted_progress = []

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        return payload

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)

    result = await JobsDBHeadedSpider().crawl(
        crawl_job_id="crawl-job-1",
        request_payload={"category_ids": [6281], "max_pages": 1, "crawl_mode": "headed", "crawl_phase": "listing"},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 0}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_listings[0]["source_job_id"] == "123456"
    assert emitted_listings[0]["listing_payload"]["title"] == "Senior Data Analyst"


@pytest.mark.asyncio
async def test_jobsdb_headed_spider_listing_phase_fetches_oldest_pages_first(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_headed_spider import JobsDBHeadedSpider
    import crawler.job_crawler.spiders.jobsdb_headed_spider as spider_module

    call_order = []
    emitted_listings = []

    page_payloads = {
        1: {
            "total_count": 60,
            "jobs": [
                {"external_id": "123456", "title": "Senior Data Analyst"},
            ],
        },
        2: {
            "total_count": 60,
            "jobs": [
                {"external_id": "123456", "title": "Senior Data Analyst"},
                {"external_id": "234567", "title": "Data Engineer"},
            ],
        },
    }

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        call_order.append(("page", page))
        return page_payloads[page]

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)
    monkeypatch.setattr(spider_module, "parse_search_response", lambda payload: payload)

    result = await JobsDBHeadedSpider().crawl(
        crawl_job_id="crawl-job-2",
        request_payload={"category_ids": [6281], "max_pages": 2, "crawl_mode": "headed", "crawl_phase": "listing"},
        emit_page_processed=lambda payload: None,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 2, "items_emitted": 0}
    assert call_order == [
        ("page", 2),
        ("page", 1),
    ]
    assert emitted_listings == [
        {
            "source_site": "jobsdb",
            "source_job_id": "123456",
            "source_url": "https://hk.jobsdb.com/job/123456",
            "source_classification_id": None,
            "source_classification_name": None,
            "listing_page": 2,
            "listing_rank": 1,
            "listing_payload": {"external_id": "123456", "title": "Senior Data Analyst"},
        },
        {
            "source_site": "jobsdb",
            "source_job_id": "234567",
            "source_url": "https://hk.jobsdb.com/job/234567",
            "source_classification_id": None,
            "source_classification_name": None,
            "listing_page": 2,
            "listing_rank": 2,
            "listing_payload": {"external_id": "234567", "title": "Data Engineer"},
        },
    ]


@pytest.mark.asyncio
async def test_jobsdb_headed_spider_detail_phase_uses_browser_detail_scraper(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_headed_spider import JobsDBHeadedSpider

    emitted_items = []
    emitted_progress = []
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")

    class FakeBrowserDetailScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(self, job_id, client=None):
            from app.sources.jobsdb.parsers import parse_detail_page

            return parse_detail_page(html, job_id=job_id)

    monkeypatch.setattr(
        "crawler.job_crawler.spiders.jobsdb_headed_spider.JobsDBBrowserDetailScraper",
        lambda *args, **kwargs: FakeBrowserDetailScraper(),
    )

    result = await JobsDBHeadedSpider().crawl(
        crawl_job_id="crawl-job-3",
        request_payload={
            "crawl_phase": "detail",
            "crawl_mode": "headed",
            "detail_targets": [
                {
                    "listing_id": "listing-1",
                    "source_listing_crawl_job_id": "listing-crawl-1",
                    "source_job_id": "123456",
                    "source_url": "https://hk.jobsdb.com/job/123456",
                    "listing_payload": {"title": "Senior Data Analyst"},
                }
            ],
        },
        emit_page_processed=lambda payload: None,
        emit_detail_progress=emitted_progress.append,
        emit_item_emitted=emitted_items.append,
    )

    assert result == {"pages_processed": 0, "items_emitted": 1}
    assert emitted_progress[0]["detail_job_total"] == 1
    assert emitted_items[0]["listing_id"] == "listing-1"
    assert emitted_items[0]["job"]["source_job_id"] == "123456"
    assert emitted_items[0]["job"]["description"] == "<p>Build & analyze</p>"
