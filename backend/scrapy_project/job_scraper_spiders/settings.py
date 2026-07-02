"""Scrapy settings for the new crawler platform project."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend directory is on sys.path so spiders can import app.*
_BACKEND_DIR = str(Path(__file__).resolve().parents[2])  # backend/
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

BOT_NAME = "job_scraper_spiders"
SPIDER_MODULES = ["job_scraper_spiders.spiders"]
NEWSPIDER_MODULE = "job_scraper_spiders.spiders"
ROBOTSTXT_OBEY = False
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
CONCURRENT_REQUESTS = 8
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [502, 503, 504, 408, 429]
TELNETCONSOLE_ENABLED = False

# --- Middleware ---
DOWNLOADER_MIDDLEWARES: dict[str, int] = {
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": 500,
    "job_scraper_spiders.downloaders.ctgoodjobs_proxy_middleware.CtgoodjobsProxyMiddleware": 550,
}

ITEM_PIPELINES: dict[str, int] = {
    "job_scraper_spiders.pipelines.postgres_pipeline.PostgresPipeline": 300,
    "job_scraper_spiders.pipelines.crawl_progress_pipeline.CrawlProgressPipeline": 100,
}

# --- Playwright (behind feature flag) ---
PLAYWRIGHT_ENABLED = False
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "timeout": 30000,
}

# --- Per-run job directory for pause/resume ---
# Override per-crawl-run via -a jobdir=... on the command line
JOBDIR = None

# --- Asyncio reactor (required by Playwright inside async callbacks) ---
# On Linux/Docker: TWISTED_REACTOR works with Playwright via the default event loop.
# On Windows: Playwright requires ProactorEventLoop for subprocess support,
# but Twisted's AsyncioSelectorReactor only accepts SelectorEventLoop.
# This is a known Windows-only limitation — production runs use Docker/Linux.
import sys as _sys
if _sys.platform != "win32":
    TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
