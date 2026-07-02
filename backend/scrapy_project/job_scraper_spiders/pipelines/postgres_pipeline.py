"""PostgreSQL pipeline — persists scraped jobs into the database."""

from __future__ import annotations

import logging
from typing import Any

import scrapy

logger = logging.getLogger(__name__)


class PostgresPipeline:
    """Scrapy pipeline that writes JobDetailItem / ListingItem to PostgreSQL.

    This is a stub for Phase 2. The full implementation in Phase 5
    will integrate with the existing SQLAlchemy repository layer.
    """

    def open_spider(self, spider: scrapy.Spider) -> None:
        logger.info("PostgresPipeline opened for spider: %s", spider.name)

    def close_spider(self, spider: scrapy.Spider) -> None:
        logger.info("PostgresPipeline closed for spider: %s", spider.name)

    def process_item(self, item: Any, spider: scrapy.Spider) -> Any:
        # Phase 5: implement actual persistence via CrawlRunRepository
        logger.debug(
            "PostgresPipeline processing item: %s from spider: %s",
            type(item).__name__,
            spider.name,
        )
        return item
