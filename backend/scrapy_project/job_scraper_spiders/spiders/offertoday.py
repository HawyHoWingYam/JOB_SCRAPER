"""OfferToday Scrapy spider.

Uses a standard request chain:
warmup page -> listing requests -> detail requests.

The search space is expanded through OfferToday's IT category tree so we can
cover the IT family broadly instead of stopping at a single keyword probe.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Iterable

import scrapy
from scrapy.http import Response

from app.sources.offertoday.search_space import build_offertoday_listing_queries
from job_scraper_spiders.items import CrawlProgressItem, JobDetailItem, ListingItem
from job_scraper_spiders.parsers.offertoday_parser import (
    build_offertoday_job_url,
    parse_detail,
    parse_listing,
    to_canonical,
)

logger = logging.getLogger(__name__)

OFFERTODAY_BASE_URL = "https://www.offertoday.com"
OFFERTODAY_LISTING_URL = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/search/list"
OFFERTODAY_DETAIL_URL_TPL = (
    f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"
)
MAX_PAGES = 9999

_COMMON_HEADERS = {
    "api-language": "zh_HK",
    "x-requested-with": "XMLHttpRequest",
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
}

_WARMUP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}


class OfferTodaySpider(scrapy.Spider):
    name = "offertoday"
    allowed_domains = ["offertoday.com"]
    custom_settings = {
        "OFFSITE_ENABLED": False,
        "COOKIES_ENABLED": False,
    }

    category_ids: str = ""
    keywords: str = ""
    max_pages: str = "100"
    publish_time_window: str = ""
    crawl_run_id: str = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._category_ids: list[int] = []

        cats = str(kwargs.get("category_ids", "") or "")
        if cats:
            self._category_ids = [int(c.strip()) for c in cats.split(",") if c.strip().isdigit()]

        self._keywords = str(kwargs.get("keywords", "") or "")

        mp = str(kwargs.get("max_pages", "100") or "100")
        try:
            self._max_pages_val = min(int(mp), MAX_PAGES)
        except ValueError:
            self._max_pages_val = 100

        self.crawl_run_id = str(kwargs.get("crawl_run_id", "") or "")
        listing_tasks = self._build_listing_tasks()
        self._search_families = list(
            dict.fromkeys(
                task["search_family"]
                for task in listing_tasks
                if str(task.get("search_family") or "").strip()
            )
        )
        self._listing_tasks = deque(listing_tasks)
        self._seen_ids: set[str] = set()
        self._seen_urls: set[str] = set()
        self._detail_targets: list[dict[str, Any]] = []
        self._listing_pages_processed = 0
        self._detail_count = 0
        self._detail_phase_started = False

    def _build_listing_tasks(self) -> list[dict[str, Any]]:
        return build_offertoday_listing_queries(
            self._category_ids,
            keywords=self._keywords or None,
            max_pages_per_query=self._max_pages_val,
        )

    def start_requests(self) -> Iterable[scrapy.Request]:
        logger.info(
            "Starting OfferToday crawl: categories=%s keywords=%s max_pages_per_query=%d",
            self._category_ids or "[default IT family]",
            self._keywords or "[blank]",
            self._max_pages_val,
        )

        yield scrapy.Request(
            url=f"{OFFERTODAY_BASE_URL}/hk/search",
            headers=_WARMUP_HEADERS,
            callback=self._warmup_done,
            errback=self._warmup_failed,
            dont_filter=True,
        )

    def _warmup_done(self, response: Response) -> Iterable[scrapy.Request | scrapy.Item]:
        logger.info("OfferToday warmup completed with status=%s", response.status)
        yield from self._next_listing_or_detail()

    def _warmup_failed(self, failure: Any) -> Iterable[scrapy.Request | scrapy.Item]:
        logger.warning("OfferToday warmup failed: %s", failure)
        yield from self._next_listing_or_detail()

    def _next_listing_or_detail(self) -> Iterable[scrapy.Request | scrapy.Item]:
        next_request = self._build_next_listing_request()
        if next_request is not None:
            yield next_request
            return

        if not self._detail_phase_started:
            self._detail_phase_started = True
            yield from self._start_detail_requests()

    def _build_next_listing_request(self) -> scrapy.Request | None:
        if not self._listing_tasks:
            return None

        task = self._listing_tasks.popleft()
        payload = self._build_listing_payload(
            category_id=task["category_id"],
            keyword=task["keyword"],
            page=task["page"],
        )
        return scrapy.Request(
            url=OFFERTODAY_LISTING_URL,
            method="POST",
            headers=_COMMON_HEADERS,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            callback=self._parse_listing_response,
            errback=self._on_listing_failed,
            cb_kwargs=task,
            dont_filter=True,
        )

    def _build_listing_payload(self, *, category_id: int, keyword: str, page: int) -> dict[str, Any]:
        payload = {
            "keyword": keyword,
            "rcdType": 7,
            "pageSize": 10,
            "page": page,
            "salaryType": 0,
            "employmentTypes": [],
            "publishTime": "",
            "experiences": [],
            "educationLevels": [],
            "benefits": [],
            "industries": [],
            "subDistrictCodes": [],
            "needShowDistance": False,
            "searchSource": None,
        }
        if category_id is not None:
            payload["jobFunctionCodes"] = [category_id]
        return payload

    def _parse_listing_response(
        self,
        response: Response,
        *,
        category_id: int,
        keyword: str,
        page: int,
        search_family: str,
    ) -> Iterable[scrapy.Request | scrapy.Item]:
        try:
            data = json.loads(response.text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "OfferToday listing parse failed for family=%s cat=%s keyword=%s page=%s: %s",
                search_family,
                category_id,
                keyword,
                page,
                exc,
            )
            yield from self._next_listing_or_detail()
            return

        if not data or data.get("code") != 0:
            logger.debug(
                "OfferToday listing returned non-success payload for cat=%s keyword=%s page=%s",
                category_id,
                keyword,
                page,
            )
            yield from self._next_listing_or_detail()
            return

        jobs = parse_listing(data)
        probe_new = 0

        for job in jobs:
            eid = str(job.get("encrypted_job_id") or "").strip()
            if not eid or eid in self._seen_ids:
                continue

            self._seen_ids.add(eid)
            url = build_offertoday_job_url(eid)
            if url in self._seen_urls:
                continue
            self._seen_urls.add(url)

            jf = job.get("job_functions") or []
            cid = str(jf[0].get("code") or "") if jf else ""
            listing_category_ids = [str(category_id)] if category_id is not None else []

            yield ListingItem(
                source_site="offertoday",
                source_job_id=eid,
                source_url=url,
                title=job.get("title", ""),
                company_name=job.get("company_name", ""),
                location=job.get("location", ""),
                salary_range=job.get("salary_range", ""),
                employment_type=job.get("employment_type", ""),
                listing_data=dict(job),
                crawl_run_id=self.crawl_run_id,
                category_ids=listing_category_ids,
                listing_rank=len(self._seen_ids),
            )

            self._detail_targets.append(
                {
                    "eid": eid,
                    "url": url,
                    "listing_data": dict(job),
                    "cid": cid,
                }
            )
            probe_new += 1

        self._listing_pages_processed += 1
        yield CrawlProgressItem(
            event_type="listing_page",
            crawl_run_id=self.crawl_run_id,
            source_site="offertoday",
            payload={
                "search_family": search_family,
                "search_families": list(self._search_families),
                "category_id": category_id,
                "keyword": keyword,
                "page": page,
                "job_ids_found": len(jobs),
                "job_ids_collected": len(self._seen_ids),
                "new_job_ids": probe_new,
                "pages_processed": self._listing_pages_processed,
                "listings_staged": len(self._detail_targets),
            },
        )

        yield from self._next_listing_or_detail()

    def _on_listing_failed(self, failure: Any) -> Iterable[scrapy.Request | scrapy.Item]:
        logger.warning("OfferToday listing request failed: %s", failure)
        yield from self._next_listing_or_detail()

    def _start_detail_requests(self) -> Iterable[scrapy.Request]:
        logger.info("Starting OfferToday detail phase for %d jobs", len(self._detail_targets))
        for target in self._detail_targets:
            eid = target["eid"]
            detail_url = OFFERTODAY_DETAIL_URL_TPL % (eid, eid)
            yield scrapy.Request(
                url=detail_url,
                headers=_COMMON_HEADERS,
                callback=self._parse_detail_response,
                errback=self._on_detail_failed,
                cb_kwargs=target,
                dont_filter=True,
            )

    def _parse_detail_response(
        self,
        response: Response,
        *,
        eid: str,
        url: str,
        listing_data: dict[str, Any],
        cid: str,
    ) -> Iterable[scrapy.Item]:
        try:
            data = json.loads(response.text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("OfferToday detail parse failed for %s: %s", eid, exc)
            yield self._build_detail_fallback(eid, url, listing_data, cid)
            return

        detail_success = bool(data and data.get("code") == 0 and data.get("data", {}).get("jobId"))
        if detail_success:
            parsed_detail = parse_detail(data)
            merged = {**listing_data, **parsed_detail}
            yield JobDetailItem(
                source_site="offertoday",
                source_job_id=eid,
                source_url=build_offertoday_job_url(eid),
                title=parsed_detail.get("title", ""),
                description_html=parsed_detail.get("description_html", ""),
                description_text=parsed_detail.get("description_text", ""),
                company_name=parsed_detail.get("company_name", ""),
                location=parsed_detail.get("location", ""),
                salary_range=parsed_detail.get("salary_range", ""),
                employment_type=parsed_detail.get("employment_type", ""),
                source_classification_id=cid or None,
                posted_date=parsed_detail.get("posted_desc", ""),
                raw_data=to_canonical(merged),
                crawl_run_id=self.crawl_run_id,
                detail_success=True,
            )
        else:
            yield self._build_detail_fallback(eid, url, listing_data, cid)

        self._detail_count += 1
        yield CrawlProgressItem(
            event_type="detail_page",
            crawl_run_id=self.crawl_run_id,
            source_site="offertoday",
            payload={
                "detail_index": self._detail_count,
                "detail_total": len(self._detail_targets),
                "detail_success": detail_success,
            },
        )

    def _on_detail_failed(self, failure: Any) -> Iterable[scrapy.Item]:
        request = getattr(failure, "request", None)
        target = getattr(request, "cb_kwargs", {}) if request is not None else {}
        eid = str(target.get("eid") or "unknown")
        url = str(target.get("url") or getattr(request, "url", "") or "")
        listing_data = target.get("listing_data") or {}
        cid = str(target.get("cid") or "")
        logger.warning("OfferToday detail request failed for %s: %s", eid, failure)
        yield self._build_detail_fallback(eid, url, listing_data, cid)

    def _build_detail_fallback(
        self,
        eid: str,
        url: str,
        listing_data: dict[str, Any],
        cid: str,
    ) -> JobDetailItem:
        return JobDetailItem(
            source_site="offertoday",
            source_job_id=eid,
            source_url=url or build_offertoday_job_url(eid),
            title=listing_data.get("title", ""),
            description_html="",
            description_text="",
            company_name=listing_data.get("company_name", ""),
            location=listing_data.get("location", ""),
            salary_range=listing_data.get("salary_range", ""),
            employment_type=listing_data.get("employment_type", ""),
            source_classification_id=cid or None,
            posted_date="",
            raw_data=to_canonical(listing_data),
            crawl_run_id=self.crawl_run_id,
            detail_success=False,
        )
