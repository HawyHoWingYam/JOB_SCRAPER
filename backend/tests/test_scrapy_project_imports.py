"""Test that the new Scrapy project can be imported and lists spiders."""

from __future__ import annotations

import sys
from pathlib import Path


SCRAPY_PROJECT_DIR = str(
    Path(__file__).resolve().parents[2] / "backend" / "scrapy_project"
)
if SCRAPY_PROJECT_DIR not in sys.path:
    sys.path.insert(0, SCRAPY_PROJECT_DIR)


class TestScrapyProjectImports:
    def test_scrapy_importable(self) -> None:
        """Scrapy itself must be installed."""
        import scrapy as _scrapy  # noqa: F811

        assert hasattr(_scrapy, "Item")

    def test_settings_importable(self) -> None:
        from job_scraper_spiders.settings import (
            BOT_NAME,
            CONCURRENT_REQUESTS,
            DOWNLOAD_TIMEOUT,
        )

        assert BOT_NAME == "job_scraper_spiders"
        assert CONCURRENT_REQUESTS == 8
        assert DOWNLOAD_TIMEOUT == 30

    def test_items_importable(self) -> None:
        from job_scraper_spiders.items import ListingItem, JobDetailItem, CrawlProgressItem

        item = ListingItem(source_site="offertoday", source_job_id="abc123", title="Engineer")
        assert item["source_site"] == "offertoday"
        assert item["title"] == "Engineer"

        detail = JobDetailItem(source_site="offertoday", source_job_id="xyz789", detail_success=True)
        assert detail["detail_success"] is True

        progress = CrawlProgressItem(
            event_type="page_processed", crawl_run_id="run-1", source_site="test"
        )
        assert progress["event_type"] == "page_processed"

    def test_scrapy_can_load_project_settings(self) -> None:
        """Verify Scrapy can load the project settings from scrapy_project dir."""
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(Path(SCRAPY_PROJECT_DIR))

            from scrapy.utils.project import get_project_settings

            settings = get_project_settings()
            assert settings["BOT_NAME"] == "job_scraper_spiders"
            assert "job_scraper_spiders.spiders" in settings["SPIDER_MODULES"]
            assert (
                "job_scraper_spiders.pipelines.postgres_pipeline.PostgresPipeline"
                in settings["ITEM_PIPELINES"]
            )
        finally:
            os.chdir(str(old_cwd))

    def test_pipeline_modules_importable(self) -> None:
        from job_scraper_spiders.pipelines.postgres_pipeline import PostgresPipeline  # noqa: F401
        from job_scraper_spiders.pipelines.crawl_progress_pipeline import (  # noqa: F401
            CrawlProgressPipeline,
        )

    def test_scrapy_list_command(self) -> None:
        """Verify `scrapy list` can discover spiders (should be empty for now)."""
        from scrapy.utils.project import get_project_settings
        from scrapy.spiderloader import SpiderLoader

        settings = get_project_settings()
        loader = SpiderLoader.from_settings(settings)
        spider_list = loader.list()
        assert isinstance(spider_list, list)
        # No spiders registered yet — this is Phase 2
