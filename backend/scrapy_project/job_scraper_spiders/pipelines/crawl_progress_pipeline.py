"""Crawl progress pipeline — emits progress events during spider execution."""

from __future__ import annotations

import logging
from typing import Any

import scrapy

logger = logging.getLogger(__name__)


class CrawlProgressPipeline:
    """Scrapy pipeline that tracks crawl-run progress for frontend visibility.

    This is a stub for Phase 2. The full implementation in Phase 5
    will update the crawl-run projection service.
    """

    def open_spider(self, spider: scrapy.Spider) -> None:
        logger.info("CrawlProgressPipeline opened for spider: %s", spider.name)

    def close_spider(self, spider: scrapy.Spider) -> None:
        logger.info("CrawlProgressPipeline closed for spider: %s", spider.name)

    def process_item(self, item: Any, spider: scrapy.Spider) -> Any:
        logger.debug(
            "CrawlProgressPipeline processing item: %s from spider: %s",
            type(item).__name__,
            spider.name,
        )
        return item
