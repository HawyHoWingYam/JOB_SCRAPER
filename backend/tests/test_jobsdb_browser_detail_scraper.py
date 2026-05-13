import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobsdb"


@pytest.mark.asyncio
async def test_jobsdb_browser_detail_scraper_parses_full_detail_html():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")

    async def fake_fetch_page_content(url: str) -> str:
        assert url.endswith("/123456")
        return html

    scraper = JobsDBBrowserDetailScraper(page_content_fetcher=fake_fetch_page_content)
    detail = await scraper.fetch_job_detail("123456")

    assert detail is not None
    assert detail["jobsdb_id"] == "123456"
    assert detail["title"] == "Senior Data Analyst"


@pytest.mark.asyncio
async def test_jobsdb_browser_detail_scraper_accepts_sync_page_content_fetcher():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")

    def fake_sync_fetch_page_content(url: str) -> str:
        assert url.endswith("/123456")
        return html

    scraper = JobsDBBrowserDetailScraper(sync_page_content_fetcher=fake_sync_fetch_page_content)
    detail = await scraper.fetch_job_detail("123456")

    assert detail is not None
    assert detail["jobsdb_id"] == "123456"


@pytest.mark.asyncio
async def test_jobsdb_browser_detail_scraper_returns_none_for_interstitial_html():
    async def fake_fetch_page_content(url: str) -> str:
        return "<html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>"

    scraper = JobsDBBrowserDetailScraper(page_content_fetcher=fake_fetch_page_content)
    detail = await scraper.fetch_job_detail("92065180")

    assert detail is None


@pytest.mark.asyncio
async def test_jobsdb_browser_detail_scraper_reuses_single_sync_browser_runtime_across_multiple_details():
    html = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
    call_log = []

    scraper = JobsDBBrowserDetailScraper()

    def fake_start_sync_runtime():
        call_log.append("start")

    def fake_stop_sync_runtime():
        call_log.append("stop")

    def fake_fetch_page_content_sync(url: str) -> str:
        call_log.append(url)
        return html

    scraper._start_sync_runtime = fake_start_sync_runtime
    scraper._stop_sync_runtime = fake_stop_sync_runtime
    scraper._fetch_page_content_sync = fake_fetch_page_content_sync

    async with scraper:
        first = await scraper.fetch_job_detail("123456")
        second = await scraper.fetch_job_detail("654321")

    assert first is not None
    assert second is not None
    assert call_log == [
        "start",
        "https://hk.jobsdb.com/job/123456",
        "https://hk.jobsdb.com/job/654321",
        "stop",
    ]
