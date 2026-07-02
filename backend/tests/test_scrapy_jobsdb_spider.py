"""Tests for the JobsDB Scrapy spider."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scrapy_project is importable
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


class TestJobsdbParser:
    """Tests for the JobsDB parser wrappers."""

    def test_parse_listing_empty(self) -> None:
        from job_scraper_spiders.parsers.jobsdb_parser import parse_listing_search

        result = parse_listing_search({"data": [], "totalCount": 0})
        assert result["total_count"] == 0
        assert result["jobs"] == []

    def test_parse_detail_html_valid(self) -> None:
        from job_scraper_spiders.parsers.jobsdb_parser import parse_detail_html

        html = (FIXTURES / "jobsdb_detail_page.html").read_text(encoding="utf-8")
        result = parse_detail_html(html, job_id="test-123-abc")
        assert result is not None
        assert result["jobsdb_id"] == "test-123-abc"

    def test_parse_detail_html_invalid_returns_none(self) -> None:
        from job_scraper_spiders.parsers.jobsdb_parser import parse_detail_html

        result = parse_detail_html("<html></html>", job_id="test-123")
        assert result is None


class TestJobsdbSpiderArgs:
    def test_default_args(self) -> None:
        from job_scraper_spiders.spiders.jobsdb import JobsdbSpider

        spider = JobsdbSpider()
        assert spider._category_ids == []
        assert spider._max_pages == 10

    def test_category_ids_parsed(self) -> None:
        from job_scraper_spiders.spiders.jobsdb import JobsdbSpider

        spider = JobsdbSpider(category_ids="6281,6282,6283")
        assert spider._category_ids == ["6281", "6282", "6283"]

    def test_max_pages_parsed(self) -> None:
        from job_scraper_spiders.spiders.jobsdb import JobsdbSpider

        spider = JobsdbSpider(max_pages="5")
        assert spider._max_pages == 5

    def test_crawl_run_id(self) -> None:
        from job_scraper_spiders.spiders.jobsdb import JobsdbSpider

        spider = JobsdbSpider(crawl_run_id="run-jobsdb-001")
        assert spider.crawl_run_id == "run-jobsdb-001"


class TestJobsdbDetailFallback:
    def test_fallback_detail_item(self) -> None:
        from job_scraper_spiders.items import JobDetailItem
        from job_scraper_spiders.spiders.jobsdb import JobsdbSpider

        spider = JobsdbSpider()
        item = spider._build_fallback_detail(
            job_id="test-123", listing_url="https://hk.jobsdb.com/job/test-123"
        )
        assert isinstance(item, JobDetailItem)
        assert item["detail_success"] is False
        assert item["source_job_id"] == "test-123"
        assert item["source_url"] == "https://hk.jobsdb.com/job/test-123"
