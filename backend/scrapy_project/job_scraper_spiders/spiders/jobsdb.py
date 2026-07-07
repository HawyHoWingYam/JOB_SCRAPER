"""JobsDB Scrapy spider — listing API + detail HTML scraping.

JobsDB uses a REST API for listing search (no WAF) and static HTML pages
for job details. This spider requires no Playwright or browser fallback
for the main path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterable

import scrapy
from scrapy.http import Response

from job_scraper_spiders.items import CrawlProgressItem, JobDetailItem, ListingItem
from job_scraper_spiders.parsers.jobsdb_parser import (
    parse_detail_html,
    parse_listing_search,
    to_canonical,
)

logger = logging.getLogger(__name__)

JOBSDB_BASE_URL = "https://hk.jobsdb.com"
JOBSDB_API_URL = f"{JOBSDB_BASE_URL}/api/jobsearch/v5/search"
JOBSDB_PAGE_SIZE = 32

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8",
}


class JobsdbSpider(scrapy.Spider):
    """Scrapy spider for JobsDB job listings and details."""

    name = "jobsdb"
    allowed_domains = ["hk.jobsdb.com", "jobsdb.com"]

    # Spider arguments
    category_ids: str = ""  # comma-separated classification IDs
    max_pages: str = "10"
    crawl_run_id: str = ""
    jobdir: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        cats = str(kwargs.get("category_ids", "") or "")
        self._category_ids = [c.strip() for c in cats.split(",") if c.strip().isdigit()]
        mp = str(kwargs.get("max_pages", "10") or "10")
        try:
            self._max_pages = int(mp)
        except ValueError:
            self._max_pages = 10

        self.crawl_run_id = str(kwargs.get("crawl_run_id", "") or "")
        self.jobdir = str(kwargs.get("jobdir", "") or "")
        self._detail_job_ids: list[tuple[str, str]] = []  # (external_id, title, source_url)
        self._detail_done: int = 0
        self._detail_total: int = 0

    def start_requests(self) -> AsyncIterable[scrapy.Request]:
        """Start with listing API requests for each category."""
        for cat_id in self._category_ids:
            for page in range(1, self._max_pages + 1):
                yield scrapy.Request(
                    url=JOBSDB_API_URL,
                    method="GET",
                    headers=_DEFAULT_HEADERS,
                    meta={"category_id": cat_id, "page": page},
                    cb_kwargs={"category_id": cat_id, "page": page},
                    callback=self._parse_listing,
                    dont_filter=True,
                )

    def _parse_listing(self, response: Response, *, category_id: str, page: int) -> AsyncIterable[scrapy.Item]:
        """Parse a listing API response."""
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("JobsDB listing JSON parse error for cat=%s page=%d: %s", category_id, page, exc)
            return

        parsed = parse_listing_search(data)
        jobs = parsed.get("jobs", [])

        if not jobs:
            logger.debug("No jobs on page %d for category %s", page, category_id)
            return

        logger.info("JobsDB listing cat=%s page=%d jobs=%d", category_id, page, len(jobs))

        for job in jobs:
            external_id = str(job.get("external_id") or "").strip()
            title = str(job.get("title") or "").strip()
            if not external_id or not title:
                continue

            listing_url = f"{JOBSDB_BASE_URL}/job/{external_id}"
            company_name = job.get("company_name") or job.get("advertiser_name") or ""

            yield ListingItem(
                source_site="jobsdb",
                source_job_id=external_id,
                source_url=listing_url,
                title=title,
                company_name=company_name,
                location=job.get("location", ""),
                salary_range=job.get("salary_label", ""),
                employment_type=", ".join(job.get("work_types", [])),
                listing_data=dict(job),
                crawl_run_id=self.crawl_run_id,
                category_ids=[category_id],
                listing_rank=0,
            )

            # Queue detail fetch
            self._detail_job_ids.append((external_id, listing_url))

        # Report listing progress
        yield CrawlProgressItem(
            event_type="listing_page",
            crawl_run_id=self.crawl_run_id,
            source_site="jobsdb",
            payload={
                "category_id": category_id,
                "page": page,
                "jobs_in_response": len(jobs),
            },
        )

        # After all listing requests finish, trigger detail phase
        if self._is_last_listing_request(category_id, page):
            yield from self._start_detail_requests()

    def _is_last_listing_request(self, category_id: str, page: int) -> bool:
        """Heuristic: trigger details after last listing page of last category."""
        if not self._category_ids:
            return False
        last_cat = self._category_ids[-1]
        last_page = self._max_pages
        return str(category_id) == str(last_cat) and page >= last_page

    def _start_detail_requests(self) -> AsyncIterable[scrapy.Request]:
        """Yield detail page requests for all discovered job IDs."""
        logger.info("Starting detail phase for %d JobsDB jobs", len(self._detail_job_ids))
        self._detail_total = len(self._detail_job_ids)
        self._detail_done = 0
        for job_id, listing_url in self._detail_job_ids:
            yield scrapy.Request(
                url=listing_url,
                headers=_DEFAULT_HEADERS,
                callback=self._parse_detail,
                cb_kwargs={"job_id": job_id, "listing_url": listing_url},
                errback=self._on_detail_failure,
                meta={"job_id": job_id, "listing_url": listing_url},
                dont_filter=True,
            )

    def _parse_detail(
        self, response: Response, *, job_id: str, listing_url: str
    ) -> AsyncIterable[scrapy.Item]:
        """Parse a detail page HTML."""
        parsed = parse_detail_html(response.text, job_id=job_id)
        if parsed is None:
            yield self._build_fallback_detail(job_id, listing_url)
            return

        canonical = to_canonical(parsed, source_url=listing_url)

        self._detail_done += 1
        if self._detail_done % 10 == 0 or self._detail_done == self._detail_total:
            logger.info(
                "JobsDB detail progress %d/%d (%.0f%%)",
                self._detail_done,
                self._detail_total,
                self._detail_done / max(self._detail_total, 1) * 100,
            )

        yield JobDetailItem(
            source_site="jobsdb",
            source_job_id=job_id,
            source_url=listing_url,
            title=parsed.get("title", canonical.get("title", "")),
            description_html=parsed.get("description_html", "") or "",
            description_text="",  # JobsDB parser returns description_html only
            company_name=parsed.get("advertiser_name", "") or "",
            location=parsed.get("location", ""),
            salary_range=canonical.get("salary_range", ""),
            employment_type=parsed.get("work_type", ""),
            source_classification_id=str(parsed.get("classification_id") or "") if parsed.get("classification_id") else None,
            source_classification_name=parsed.get("classification", ""),
            posted_date=parsed.get("listing_date", ""),
            raw_data=canonical,
            crawl_run_id=self.crawl_run_id,
            detail_success=True,
        )

    def _on_detail_failure(self, failure: Any) -> AsyncIterable[scrapy.Item]:
        """Handle detail page fetch failure."""
        job_id = failure.request.meta.get("job_id", "unknown")
        listing_url = failure.request.meta.get("listing_url", "")
        self._detail_done += 1
        yield self._build_fallback_detail(job_id, listing_url)

    def _build_fallback_detail(self, job_id: str, listing_url: str) -> JobDetailItem:
        """Build a detail item with detail_success=False when detail fetch fails."""
        return JobDetailItem(
            source_site="jobsdb",
            source_job_id=job_id,
            source_url=listing_url,
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
            crawl_run_id=self.crawl_run_id,
            detail_success=False,
        )

    def spider_closed(self, spider):
        logger.info(
            "JobsDB spider finished: detail_done=%d detail_total=%d",
            self._detail_done,
            self._detail_total,
        )
