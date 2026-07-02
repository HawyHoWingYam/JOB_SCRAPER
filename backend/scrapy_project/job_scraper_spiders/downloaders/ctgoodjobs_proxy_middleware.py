"""CTGoodJobs downloader middleware — proxy rotation + Cloudflare challenge detection.

This middleware intercepts requests/responses for CTGoodJobs and:
1. Provides proxy lease management (re-using the legacy proxy rotation runtime)
2. Detects Cloudflare challenge pages
3. Reports proxy success/failure metrics

Designed to replace the custom source-specific downloader loop currently
in the CTgoodjobs spider code.
"""

from __future__ import annotations

import logging
from typing import Any

import scrapy
from scrapy import signals
from scrapy.http import HtmlResponse, Request, Response

logger = logging.getLogger(__name__)

_INTERSTITIAL_MARKERS = (
    "just a moment",
    "cf-challenge",
    "challenges.cloudflare.com",
    "verify you are human",
    "lets confirm you are human",
    "complete the security check before continuing",
)


class CtgoodjobsProxyMiddleware:
    """Downloader middleware for CTGoodJobs proxy and challenge handling.

    This is a stub for Phase 8. The full implementation will integrate
    with the legacy CTGoodJobsProxyRuntime for proxy lease management.
    """

    def __init__(self, crawler: scrapy.Crawler) -> None:
        self.crawler = crawler
        self._challenge_count = 0
        self._proxy_success_count = 0
        self._proxy_failure_count = 0

    @classmethod
    def from_crawler(cls, crawler: scrapy.Crawler) -> CtgoodjobsProxyMiddleware:
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def process_request(
        self, request: Request, spider: scrapy.Spider
    ) -> Request | Response | None:
        """Apply proxy and headers for CTGoodJobs requests."""
        if spider.name != "ctgoodjobs":
            return None

        # Stub: In production, apply proxy from CTGoodJobsProxyRuntime here
        # Proxy is handled upstream; this middleware detects challenges.
        return None

    def process_response(
        self, request: Request, response: Response, spider: scrapy.Spider
    ) -> Request | Response:
        """Detect Cloudflare challenges and log them."""
        if spider.name != "ctgoodjobs":
            return response

        if response.status in (502, 503, 504):
            logger.warning("CTGoodJobs transient status %d for %s", response.status, request.url)
            self._proxy_failure_count += 1
            # Retry via Scrapy's built-in retry middleware
            return response

        body_text = ""
        try:
            body_text = response.text[:2000].lower()
        except Exception:
            pass

        if any(marker in body_text for marker in _INTERSTITIAL_MARKERS):
            logger.warning("CTGoodJobs challenge detected for %s", request.url)
            self._challenge_count += 1
            self._proxy_failure_count += 1
            # Mark for retry with new proxy
            response.request.meta["ctgoodjobs_challenge"] = True
            return response

        self._proxy_success_count += 1
        return response

    def spider_closed(self, spider: scrapy.Spider) -> None:
        if spider.name == "ctgoodjobs":
            logger.info(
                "CTGoodJobs proxy stats: challenges=%d success=%d failures=%d",
                self._challenge_count,
                self._proxy_success_count,
                self._proxy_failure_count,
            )
