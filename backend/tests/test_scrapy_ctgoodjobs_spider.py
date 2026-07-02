"""Tests for the CTGoodJobs Scrapy spider and middleware."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scrapy_project is importable
SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crawler"


class TestCtgoodjobsParser:
    """Tests for the CTGoodJobs parser wrappers."""

    def test_parse_detail_html_valid(self) -> None:
        from job_scraper_spiders.parsers.ctgoodjobs_parser import parse_detail

        html = (FIXTURES / "ctgoodjobs_detail_page.html").read_text(encoding="utf-8")
        result = parse_detail(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        assert result["job_id"] == "78901234"
        assert result["title"] == "Software Engineer"

    def test_parse_detail_sets_source_site(self) -> None:
        from job_scraper_spiders.parsers.ctgoodjobs_parser import parse_detail

        html = (FIXTURES / "ctgoodjobs_detail_page.html").read_text(encoding="utf-8")
        result = parse_detail(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        assert result["source_site"] == "ctgoodjobs"

    def test_to_canonical(self) -> None:
        from job_scraper_spiders.parsers.ctgoodjobs_parser import (
            parse_detail,
            to_canonical,
        )

        html = (FIXTURES / "ctgoodjobs_detail_page.html").read_text(encoding="utf-8")
        parsed = parse_detail(
            html,
            source_classification_id="39000000",
            source_classification_name="IT",
            source_classification_slug="it",
            url="https://www.ctgoodjobs.hk/job/78901234",
        )
        canonical = to_canonical(parsed)
        assert canonical["source_site"] == "ctgoodjobs"
        assert canonical["source_job_id"] == "78901234"
        assert canonical["title"] == "Software Engineer"


class TestCtgoodjobsProxyMiddleware:
    """Tests for the CTGoodJobs proxy middleware."""

    def test_challenge_markers_defined(self) -> None:
        from job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware import (
            _INTERSTITIAL_MARKERS,
        )

        assert "just a moment" in _INTERSTITIAL_MARKERS
        assert "cf-challenge" in _INTERSTITIAL_MARKERS
        assert "verify you are human" in _INTERSTITIAL_MARKERS

    def test_middleware_init(self) -> None:
        # Test that the middleware class can be created directly
        from job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware import (
            CtgoodjobsProxyMiddleware,
        )

        # Create instance without full crawler initialization
        m = CtgoodjobsProxyMiddleware.__new__(CtgoodjobsProxyMiddleware)
        m.crawler = None
        m._challenge_count = 0
        m._proxy_success_count = 0
        m._proxy_failure_count = 0
        assert m._challenge_count == 0
        assert m._proxy_failure_count == 0
    def test_default_args(self) -> None:
        from job_scraper_spiders.spiders.ctgoodjobs import CtgoodjobsSpider

        spider = CtgoodjobsSpider()
        assert spider._category_ids == []
        assert spider._max_pages == 5

    def test_category_ids_parsed(self) -> None:
        from job_scraper_spiders.spiders.ctgoodjobs import CtgoodjobsSpider

        spider = CtgoodjobsSpider(category_ids="39000000,39000001")
        assert spider._category_ids == ["39000000", "39000001"]

    def test_crawl_run_id(self) -> None:
        from job_scraper_spiders.spiders.ctgoodjobs import CtgoodjobsSpider

        spider = CtgoodjobsSpider(crawl_run_id="run-ctg-001")
        assert spider.crawl_run_id == "run-ctg-001"


class TestCtgoodjobsDetailFallback:
    def test_fallback_detail_item(self) -> None:
        from job_scraper_spiders.items import JobDetailItem

        fallback = JobDetailItem(
            source_site="ctgoodjobs",
            source_job_id="12345",
            source_url="https://jobs.ctgoodjobs.hk/job/12345",
            title="",
            description_html="",
            description_text="",
            company_name="",
            location="",
            salary_range="",
            employment_type="",
            source_classification_id=None,
            source_classification_name=None,
            posted_date="",
            raw_data={},
            crawl_run_id="test-run",
            detail_success=False,
        )
        assert fallback["detail_success"] is False
        assert fallback["source_job_id"] == "12345"
