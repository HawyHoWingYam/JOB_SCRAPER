"""Tests for the OfferToday Scrapy spider.

These tests verify the spider's parsing and item logic without requiring
live network access. They use the frozen fixtures from Phase 1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure scrapy_project is importable
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestOffertodayParser:
    """Tests that the spider's parser wrappers produce correct results."""

    def test_parse_listing_fixture(self) -> None:
        from job_scraper_spiders.parsers.offertoday_parser import parse_listing

        data = _load_json("offertoday_listing_response.json")
        jobs = parse_listing(data)
        assert len(jobs) == 2

    def test_parse_detail_fixture(self) -> None:
        from job_scraper_spiders.parsers.offertoday_parser import parse_detail

        data = _load_json("offertoday_detail_response.json")
        detail = parse_detail(data)
        assert detail["encrypted_job_id"] == "abc123=="
        assert detail["title"] == "Senior Developer"

    def test_to_canonical_listing(self) -> None:
        from job_scraper_spiders.parsers.offertoday_parser import (
            parse_listing,
            to_canonical,
        )

        data = _load_json("offertoday_listing_response.json")
        jobs = parse_listing(data)
        canonical = to_canonical(jobs[0])
        assert canonical["source_site"] == "offertoday"
        assert canonical["source_job_id"] == "abc123=="
        assert canonical["title"] == "Software Engineer"

    def test_to_canonical_detail(self) -> None:
        from job_scraper_spiders.parsers.offertoday_parser import (
            parse_detail,
            to_canonical,
        )

        data = _load_json("offertoday_detail_response.json")
        detail = parse_detail(data)
        canonical = to_canonical(detail)
        assert canonical["source_site"] == "offertoday"
        assert canonical["source_job_id"] == "abc123=="
        assert canonical["title"] == "Senior Developer"


class TestOffertodaySpiderItems:
    """Tests for the spider's item construction."""

    def test_listing_item_construction(self) -> None:
        from job_scraper_spiders.items import ListingItem

        item = ListingItem(
            source_site="offertoday",
            source_job_id="abc123==",
            source_url="https://www.offertoday.com/hk/job/abc123==",
            title="Software Engineer",
            company_name="Tech Corp",
            location="Hong Kong",
            salary_range="$30K-50K/月",
            employment_type="全職",
            listing_data={"key": "value"},
            crawl_run_id="test-run-001",
            category_ids=["112000"],
            listing_rank=1,
        )
        assert item["source_site"] == "offertoday"
        assert item["source_job_id"] == "abc123=="
        assert item["listing_rank"] == 1

    def test_job_detail_item_construction(self) -> None:
        from job_scraper_spiders.items import JobDetailItem

        item = JobDetailItem(
            source_site="offertoday",
            source_job_id="abc123==",
            source_url="https://www.offertoday.com/hk/job/abc123==",
            title="Senior Developer",
            description_html="<p>Details</p>",
            description_text="Details",
            company_name="Big Corp",
            location="Hong Kong",
            salary_range="$50K-80K/月",
            employment_type="全職",
            source_classification_id="offertoday:112000",
            source_classification_name="工程師",
            posted_date="2026-06-17",
            raw_data={"canonical": "data"},
            crawl_run_id="test-run-001",
            detail_success=True,
        )
        assert item["detail_success"] is True
        assert item["title"] == "Senior Developer"
        assert item["raw_data"]["canonical"] == "data"

    def test_detail_item_with_fallback(self) -> None:
        """Detail failure should still emit an item with detail_success=False."""
        from job_scraper_spiders.items import JobDetailItem

        item = JobDetailItem(
            source_site="offertoday",
            source_job_id="xyz789==",
            source_url="https://www.offertoday.com/hk/job/xyz789==",
            title="Data Analyst (Fallback)",
            description_html="",
            description_text="",
            company_name="Data Co",
            location="Kowloon",
            salary_range="$25K-40K/月",
            employment_type="全職",
            source_classification_id=None,
            source_classification_name=None,
            posted_date="",
            raw_data={"canonical": "fallback"},
            crawl_run_id="test-run-001",
            detail_success=False,
        )
        assert item["detail_success"] is False
        assert item["description_html"] == ""

    def test_progress_item_construction(self) -> None:
        from job_scraper_spiders.items import CrawlProgressItem

        item = CrawlProgressItem(
            event_type="listing_completed",
            crawl_run_id="test-run-001",
            source_site="offertoday",
            payload={"job_ids_found": 100, "pages_processed": 10},
        )
        assert item["event_type"] == "listing_completed"
        assert item["payload"]["job_ids_found"] == 100


class TestOffertodaySpiderArgParsing:
    """Tests for spider argument parsing."""

    def test_default_args(self) -> None:
        """Spider with no args should use defaults."""
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider()
        assert spider._category_ids == []
        assert spider._max_pages_val == 100

    def test_default_it_search_space_when_no_categories(self) -> None:
        from app.sources.offertoday.search_space import (
            DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS,
            DEFAULT_OFFERTODAY_IT_KEYWORDS,
        )
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider()
        assert len(spider._listing_tasks) > 0
        assert spider._listing_tasks[0]["search_family"] == "it_category"
        assert spider._listing_tasks[0]["category_id"] == 118000
        assert spider._listing_tasks[0]["keyword"] == ""
        assert spider._listing_tasks[0]["page"] == 1

        keyword_page_one = [
            task
            for task in spider._listing_tasks
            if task["search_family"] == "it_keyword" and task["page"] == 1
        ]
        assert [task["keyword"] for task in keyword_page_one] == list(DEFAULT_OFFERTODAY_IT_KEYWORDS)

        hybrid_page_one = [
            task
            for task in spider._listing_tasks
            if task["search_family"] == "it_hybrid" and task["page"] == 1
        ]
        assert [task["keyword"] for task in hybrid_page_one] == list(
            DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS
        )
        assert list(spider._search_families) == ["it_category", "it_keyword", "it_hybrid"]

    def test_category_ids_parsed(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(category_ids="112000,112001,112002")
        assert spider._category_ids == [112000, 112001, 112002]

    def test_single_category_id(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(category_ids="112000")
        assert spider._category_ids == [112000]

    def test_max_pages_parsed(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(max_pages="50")
        assert spider._max_pages_val == 50

    def test_max_pages_capped(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(max_pages="99999")
        assert spider._max_pages_val <= 9999

    def test_crawl_run_id(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(crawl_run_id="run-abc-123")
        assert spider.crawl_run_id == "run-abc-123"

    def test_start_requests_bootstrap(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(category_ids="112000", max_pages="2")
        requests = list(spider.start_requests())

        assert len(requests) == 1
        assert requests[0].url == "https://www.offertoday.com/hk/search"
        assert requests[0].callback.__name__ == "_warmup_done"
        assert len(spider._listing_tasks) == 2

    def test_explicit_erp_probe_is_not_overwritten(self) -> None:
        from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

        spider = OfferTodaySpider(category_ids="", keywords="ERP", max_pages="2")
        queries = spider._build_listing_tasks()

        assert queries == [
            {
                "search_family": "explicit_keyword",
                "category_id": None,
                "keyword": "ERP",
                "page": 1,
            },
            {
                "search_family": "explicit_keyword",
                "category_id": None,
                "keyword": "ERP",
                "page": 2,
            },
        ]
