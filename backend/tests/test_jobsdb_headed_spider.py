import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


@pytest.mark.asyncio
async def test_jobsdb_headed_spider_uses_browser_detail_scraper(monkeypatch):
    from crawler.job_crawler.spiders.jobsdb_headed_spider import JobsDBHeadedSpider

    payload = json.loads((FIXTURES / "search_response.json").read_text(encoding="utf-8"))
    emitted_items = []
    emitted_progress = []
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")

    async def fake_fetch_page(self, classification_id, page=1, client=None):
        return payload

    class FakeBrowserDetailScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(self, job_id, client=None):
            from app.sources.jobsdb.parsers import parse_detail_page

            return parse_detail_page(html, job_id=job_id)

    monkeypatch.setattr("app.scraper.category_scraper.CategoryListScraper.fetch_page", fake_fetch_page)
    monkeypatch.setattr(
        "crawler.job_crawler.spiders.jobsdb_headed_spider.JobsDBBrowserDetailScraper",
        lambda *args, **kwargs: FakeBrowserDetailScraper(),
    )

    result = await JobsDBHeadedSpider().crawl(
        crawl_job_id="crawl-job-1",
        request_payload={"category_ids": [6281], "max_pages": 1, "crawl_mode": "headed"},
        emit_page_processed=emitted_progress.append,
        emit_item_emitted=emitted_items.append,
    )

    assert result == {"pages_processed": 1, "items_emitted": 1}
    assert emitted_progress[0]["job_ids_collected"] == 1
    assert emitted_items[0]["source_job_id"] == "123456"
    assert emitted_items[0]["description"] == "<p>Build & analyze</p>"
