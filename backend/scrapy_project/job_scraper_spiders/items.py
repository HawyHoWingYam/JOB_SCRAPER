"""Spider items for the new scrapy-based crawler platform."""

from __future__ import annotations

from typing import Any

import scrapy


class ListingItem(scrapy.Item):
    """A job listing discovered during the listing/crawl phase."""

    source_site = scrapy.Field()
    source_job_id = scrapy.Field()
    source_url = scrapy.Field()
    title = scrapy.Field()
    company_name = scrapy.Field()
    location = scrapy.Field()
    salary_range = scrapy.Field()
    employment_type = scrapy.Field()
    listing_data = scrapy.Field()  # raw parsed listing dict
    crawl_run_id = scrapy.Field()
    category_ids = scrapy.Field()  # list of str
    listing_rank = scrapy.Field()


class JobDetailItem(scrapy.Item):
    """A fully scraped job detail, ready for ingestion."""

    source_site = scrapy.Field()
    source_job_id = scrapy.Field()
    source_url = scrapy.Field()
    title = scrapy.Field()
    description_html = scrapy.Field()
    description_text = scrapy.Field()
    company_name = scrapy.Field()
    location = scrapy.Field()
    salary_range = scrapy.Field()
    employment_type = scrapy.Field()
    source_classification_id = scrapy.Field()
    source_classification_name = scrapy.Field()
    posted_date = scrapy.Field()
    raw_data = scrapy.Field()
    crawl_run_id = scrapy.Field()
    detail_success = scrapy.Field()  # bool


class CrawlProgressItem(scrapy.Item):
    """Crawl run progress event emitted during spider execution."""

    event_type = scrapy.Field()
    crawl_run_id = scrapy.Field()
    source_site = scrapy.Field()
    payload = scrapy.Field()
