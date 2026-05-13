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
async def test_jobsdb_spider_emits_listing_fallback_when_detail_fetch_returns_none(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_spider import JobsDBSpider

    payload = json.loads((FIXTURES / "search_response.json").read_text(encoding="utf-8"))
    emitted_items = []
    emitted_progress = []

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        return payload

    async def fake_fetch_job_detail(self, job_id, client=None):
        return None

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)
    monkeypatch.setattr("app.scraper.job_detail_scraper.JobDetailScraper.fetch_job_detail", fake_fetch_job_detail)

    result = await JobsDBSpider().crawl(
        crawl_job_id="crawl-job-1",
        request_payload={"category_ids": [6281], "max_pages": 1},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=emitted_items.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 1}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_items == [
        {
            "source_site": "jobsdb",
            "source_job_id": "123456",
            "source_url": "https://hk.jobsdb.com/job/123456",
            "title": "Senior Data Analyst",
            "description": "Build reports\n\nHighlights:\n- Analyze data\n- Build reports",
            "company_name": "ACME Ltd",
            "location": "Hong Kong",
            "salary_range": "HK$30,000 - HK$40,000",
            "employment_type": "Full-time, Permanent",
            "source_classification_id": "6281",
            "source_classification_name": "Information & Communication Technology",
            "source_subclassification_id": None,
            "source_subclassification_name": None,
            "posted_date": "2026-05-01T12:00:00+00:00",
            "raw_data": {
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
