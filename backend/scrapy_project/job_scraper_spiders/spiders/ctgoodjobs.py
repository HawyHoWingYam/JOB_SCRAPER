"""CTGoodJobs Scrapy spider — category listing + detail scraping with proxy.

CTGoodJobs uses server-rendered HTML with some Cloudflare protection.
This spider relies on the CtgoodjobsProxyMiddleware for proxy rotation
and challenge detection.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterable

import scrapy
from scrapy.http import Response

from app.scraper.ctgoodjobs.category_registry import (
    CTGOODJOBS_BASE_URL,
)
from app.scraper.ctgoodjobs.list_scraper import category_page_url
from app.source_catalog.runtime import load_published_query_plan
from job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware import (  # noqa: F401 — register middleware
    CtgoodjobsProxyMiddleware,
)
from job_scraper_spiders.items import CrawlProgressItem, JobDetailItem, ListingItem
from job_scraper_spiders.parsers.ctgoodjobs_parser import (
    parse_category,
    parse_detail,
    to_canonical,
)

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,en-HK;q=0.9,en;q=0.8,zh-CN;q=0.7",
}


class CtgoodjobsSpider(scrapy.Spider):
    """Scrapy spider for CTGoodJobs job listings and details."""

    name = "ctgoodjobs"
    allowed_domains = ["ctgoodjobs.hk", "jobs.ctgoodjobs.hk"]
    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": False},
    }

    # Spider arguments
    category_ids: str = ""  # comma-separated source_classification_ids
    max_pages: str = "5"
    crawl_run_id: str = ""
    jobdir: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        cats = str(kwargs.get("category_ids", "") or "")
        self._category_ids = [c.strip() for c in cats.split(",") if c.strip()]
        mp = str(kwargs.get("max_pages", "5") or "5")
        try:
            self._max_pages = int(mp)
        except ValueError:
            self._max_pages = 5

        self.crawl_run_id = str(kwargs.get("crawl_run_id", "") or "")
        self.jobdir = str(kwargs.get("jobdir", "") or "")
        self._detail_done: int = 0
        self._detail_total: int = 0

    def start_requests(self) -> AsyncIterable[scrapy.Request]:
        """Start with category listing page requests."""
        plan = load_published_query_plan("ctgoodjobs", self._category_ids)
        for entry in plan.entries:
            cat_id = entry.node.classification_id
            cat_name = entry.node.native_label
            slug = str(entry.node.source_metadata.get("slug") or "")
            url_path = str(entry.target.payload["url_path"])
            base_url = f"{CTGOODJOBS_BASE_URL}{url_path}"

            for page in range(1, self._max_pages + 1):
                url = category_page_url(base_url, page=page)

                yield scrapy.Request(
                    url=url,
                    headers=_DEFAULT_HEADERS,
                    callback=self._parse_listing_page,
                    cb_kwargs={
                        "category_id": cat_id,
                        "category_name": cat_name,
                        "slug": slug,
                        "page": page,
                        "url": url,
                    },
                    meta={
                        "playwright": True,
                        "source_catalog_revision_id": str(plan.revision_id),
                        "source_catalog_fingerprint": plan.revision_fingerprint,
                    },
                    dont_filter=True,
                )

    def _parse_listing_page(
        self,
        response: Response,
        *,
        category_id: str,
        category_name: str,
        slug: str,
        page: int,
        url: str,
    ) -> AsyncIterable[scrapy.Item]:
        """Parse a category listing page."""
        parsed = parse_category(
            response.text,
            category_slug=slug,
            source_classification_id=category_id,
            source_classification_name=category_name,
            page=page,
            url=url,
        )

        job_ids = parsed.get("job_ids", [])
        job_urls = parsed.get("job_urls", [])
        errors = parsed.get("errors", [])

        if errors:
            logger.warning("CTGoodJobs listing page %d cat=%s errors: %s", page, category_id, errors)

        logger.info("CTGoodJobs listing cat=%s page=%d jobs=%d", category_id, page, len(job_ids))

        for job_id, job_url in zip(job_ids, job_urls):
            yield ListingItem(
                source_site="ctgoodjobs",
                source_job_id=str(job_id),
                source_url=job_url,
                title="",
                company_name="",
                location="",
                salary_range="",
                employment_type="",
                listing_data={"category_id": category_id, "category_name": category_name},
                crawl_run_id=self.crawl_run_id,
                category_ids=[category_id],
                listing_rank=0,
            )

            # Trigger detail fetch
            yield scrapy.Request(
                url=job_url,
                headers=_DEFAULT_HEADERS,
                callback=self._parse_detail_page,
                cb_kwargs={
                    "job_id": str(job_id),
                    "job_url": job_url,
                    "category_id": category_id,
                    "category_name": category_name,
                    "slug": slug,
                },
                errback=self._on_detail_failure,
                meta={"job_id": str(job_id), "ctgoodjobs_request": True},
                dont_filter=True,
            )

        yield CrawlProgressItem(
            event_type="listing_page",
            crawl_run_id=self.crawl_run_id,
            source_site="ctgoodjobs",
            payload={
                "category_id": category_id,
                "page": page,
                "job_ids_found": len(job_ids),
                "errors": errors,
            },
        )

    def _parse_detail_page(
        self,
        response: Response,
        *,
        job_id: str,
        job_url: str,
        category_id: str,
        category_name: str,
        slug: str,
    ) -> AsyncIterable[scrapy.Item]:
        """Parse a job detail page."""
        parsed = parse_detail(
            response.text,
            source_classification_id=category_id,
            source_classification_name=category_name,
            source_classification_slug=slug,
            url=job_url,
        )

        canonical = to_canonical(parsed)

        self._detail_done += 1
        if self._detail_done % 10 == 0:
            logger.info("CTGoodJobs detail %d done", self._detail_done)

        yield JobDetailItem(
            source_site="ctgoodjobs",
            source_job_id=job_id,
            source_url=job_url,
            title=parsed.get("title", canonical.get("title", "")),
            description_html=parsed.get("description_html", ""),
            description_text=parsed.get("description_text", ""),
            company_name=parsed.get("company_name", ""),
            location=parsed.get("location", ""),
            salary_range=parsed.get("salary_range", ""),
            employment_type=parsed.get("employment_type", ""),
            source_classification_id=category_id,
            source_classification_name=category_name,
            posted_date=parsed.get("posted_date", ""),
            raw_data=canonical,
            crawl_run_id=self.crawl_run_id,
            detail_success=True,
        )

    def _on_detail_failure(self, failure: Any) -> AsyncIterable[scrapy.Item]:
        """Handle detail page fetch failure."""
        job_id = failure.request.meta.get("job_id", "unknown")
        job_url = failure.request.url if hasattr(failure.request, "url") else ""
        self._detail_done += 1
        yield JobDetailItem(
            source_site="ctgoodjobs",
            source_job_id=job_id,
            source_url=job_url,
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
            "CTGoodJobs spider finished: details_done=%d",
            self._detail_done,
        )
