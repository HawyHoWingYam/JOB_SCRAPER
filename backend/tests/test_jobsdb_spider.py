from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.sources.jobsdb import parsers


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


def test_jobsdb_spider_builds_canonical_item_from_parsed_detail():
    from crawler.job_crawler.spiders.jobsdb_spider import build_canonical_job

    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    parsed = parsers.parse_detail_page(html, job_id="123456")
    item = build_canonical_job(parsed, source_url="https://hk.jobsdb.com/job/123456")

    assert item.source_site == "jobsdb"
    assert item.source_job_id == "123456"
    assert item.source_url == "https://hk.jobsdb.com/job/123456"
    assert item.title == "Senior Data Analyst"


@pytest.mark.asyncio
async def test_jobsdb_spider_listing_phase_emits_staging_rows(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_spider import JobsDBSpider

    payload = json.loads((FIXTURES / "search_response.json").read_text(encoding="utf-8"))
    emitted_listings = []
    emitted_progress = []

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        return payload

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)

    result = await JobsDBSpider().crawl(
        crawl_job_id="crawl-job-1",
        request_payload={"category_ids": [6281], "max_pages": 1, "crawl_phase": "listing"},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=lambda payload: None,
        emit_listing_emitted=emitted_listings.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 0}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_listings == [
        {
            "source_site": "jobsdb",
            "source_job_id": "123456",
            "source_url": "https://hk.jobsdb.com/job/123456",
            "source_classification_id": "6281",
            "source_classification_name": "Information & Communication Technology",
            "listing_page": 1,
            "listing_rank": 1,
            "listing_payload": {
                "external_id": "123456",
                "title": "Senior Data Analyst",
                "company_name": "ACME Ltd",
                "advertiser_id": "adv-1",
                "advertiser_name": "ACME Ltd",
                "bullet_points": ["Analyze data", "Build reports"],
                "location": "Hong Kong",
                "country_code": "HK",
                "salary_label": "HK$30,000 - HK$40,000",
                "listing_date": "2026-05-01T12:00:00+00:00",
                "listing_date_display": "1 May 2026",
                "teaser": "Build reports",
                "work_types": ["Full-time", "Permanent"],
                "work_arrangements": ["Hybrid"],
                "classification_id": "6281",
                "classification_name": "Information & Communication Technology",
                "logo_url": "https://example.com/logo.png",
            },
        }
    ]


@pytest.mark.asyncio
async def test_jobsdb_spider_listing_phase_fetches_oldest_pages_first(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_spider import JobsDBSpider
    import crawler.job_crawler.spiders.jobsdb_spider as spider_module

    call_order = []
    emitted_listings = []

    page_payloads = {
        1: {
            "total_count": 60,
            "jobs": [
                {
                    "external_id": "123456",
                    "title": "Senior Data Analyst",
                }
            ],
        },
        2: {
            "total_count": 60,
            "jobs": [
                {
                    "external_id": "123456",
                    "title": "Senior Data Analyst",
                },
                {
                    "external_id": "234567",
                    "title": "Data Engineer",
                },
            ],
        },
    }

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        call_order.append(("page", page))
        return page_payloads[page]

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)
    monkeypatch.setattr(spider_module, "parse_search_response", lambda payload: payload)

    result = await JobsDBSpider().crawl(
        crawl_job_id="crawl-job-2",
        request_payload={"category_ids": [6281], "max_pages": 2, "crawl_phase": "listing"},
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
            "listing_payload": {
                "external_id": "123456",
                "title": "Senior Data Analyst",
            },
        },
        {
            "source_site": "jobsdb",
            "source_job_id": "234567",
            "source_url": "https://hk.jobsdb.com/job/234567",
            "source_classification_id": None,
            "source_classification_name": None,
            "listing_page": 2,
            "listing_rank": 2,
            "listing_payload": {
                "external_id": "234567",
                "title": "Data Engineer",
            },
        },
    ]


@pytest.mark.asyncio
async def test_jobsdb_spider_detail_phase_processes_targets_and_marks_completion(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_spider import JobsDBSpider

    emitted_items = []
    detail_progress = []
    running_targets = []
    completed_targets = []

    async def fake_fetch_job_detail(self, job_id, client=None):
        return {
            "jobsdb_id": job_id,
            "title": "Senior Data Analyst",
            "description_html": "<p>Build reports</p>",
            "classification_id": "6281",
            "classification": "Information & Communication Technology",
            "subclassification_id": "6282",
            "subclassification": "Data Science",
            "location": "Hong Kong",
            "work_type": "Full-time",
            "salary": "HK$30,000 - HK$40,000",
            "listing_date": "2026-05-01T12:00:00+00:00",
            "advertiser_id": "adv-1",
            "advertiser_name": "ACME Ltd",
        }

    monkeypatch.setattr("app.scraper.job_detail_scraper.JobDetailScraper.fetch_job_detail", fake_fetch_job_detail)

    result = await JobsDBSpider().crawl(
        crawl_job_id="crawl-job-3",
        request_payload={
            "crawl_phase": "detail",
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
        emit_detail_progress=detail_progress.append,
        emit_item_emitted=emitted_items.append,
        mark_detail_running=running_targets.append,
        mark_detail_completed=lambda target, detail_payload: completed_targets.append((target, detail_payload)),
    )

    assert result == {"pages_processed": 0, "items_emitted": 1}
    assert running_targets == [
        {
            "listing_id": "listing-1",
            "source_listing_crawl_job_id": "listing-crawl-1",
            "source_job_id": "123456",
            "source_url": "https://hk.jobsdb.com/job/123456",
            "listing_payload": {"title": "Senior Data Analyst"},
        }
    ]
    assert detail_progress[0]["detail_job_index"] == 1
    assert detail_progress[0]["detail_job_total"] == 1
    assert completed_targets[0][0]["listing_id"] == "listing-1"
    assert emitted_items[0]["listing_id"] == "listing-1"
    assert emitted_items[0]["job"]["source_job_id"] == "123456"
