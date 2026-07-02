"""Tests for the CTGoodJobs proxy middleware."""

from __future__ import annotations

import sys
from pathlib import Path

SCRAPY_PROJECT = str(Path(__file__).resolve().parents[1] / "scrapy_project")
if SCRAPY_PROJECT not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT)


class TestCtgoodjobsProxyMiddleware:
    def test_challenge_markers_defined(self) -> None:
        from job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware import (
            _INTERSTITIAL_MARKERS,
        )

        assert "just a moment" in _INTERSTITIAL_MARKERS
        assert "cf-challenge" in _INTERSTITIAL_MARKERS
        assert "verify you are human" in _INTERSTITIAL_MARKERS

    def test_middleware_init_from_crawler(self) -> None:
        from job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware import (
            CtgoodjobsProxyMiddleware,
        )

        # Direct instantiation (bypass from_crawler for unit test)
        middleware = CtgoodjobsProxyMiddleware.__new__(CtgoodjobsProxyMiddleware)
        middleware.crawler = None
        middleware._challenge_count = 0
        middleware._proxy_success_count = 0
        middleware._proxy_failure_count = 0
        assert middleware._challenge_count == 0
        assert middleware._proxy_success_count == 0
        assert middleware._proxy_failure_count == 0
