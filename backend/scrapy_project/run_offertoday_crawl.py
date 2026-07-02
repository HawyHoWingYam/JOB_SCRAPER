#!/usr/bin/env python3
"""Wrapper script to run an OfferToday spider crawl via CrawlerProcess.

Scrapy 2.16 CLI's signal dispatcher doesn't handle async callbacks natively.
Using CrawlerProcess directly works because it properly sets up the asyncio reactor.

Usage:
    python run_offertoday_crawl.py --category-ids 112000 --max-pages 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure paths
BACKEND = str(Path(__file__).resolve().parents[1] / "app")
if BACKEND not in sys.path:
    sys.path.insert(0, str(Path(BACKEND).parent))
SCRAPY = str(Path(__file__).resolve().parent)
if SCRAPY not in sys.path:
    sys.path.insert(0, SCRAPY)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OfferToday spider crawl")
    parser.add_argument("--category-ids", type=str, default="112000", help="Comma-separated category IDs")
    parser.add_argument("--max-pages", type=int, default=100, help="Max pages to crawl")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    args = parser.parse_args()

    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    from job_scraper_spiders.spiders.offertoday import OfferTodaySpider

    settings = get_project_settings()
    settings.set("LOG_LEVEL", args.log_level)

    process = CrawlerProcess(settings)
    process.crawl(
        OfferTodaySpider,
        category_ids=args.category_ids,
        max_pages=str(args.max_pages),
    )
    process.start()


if __name__ == "__main__":
    main()
