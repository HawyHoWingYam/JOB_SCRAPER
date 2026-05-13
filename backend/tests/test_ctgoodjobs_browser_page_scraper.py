from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_returns_rendered_html():
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper

    async def fake_fetch_page_content(url: str) -> str:
        assert url == "https://jobs.ctgoodjobs.hk/jobs"
        return "<html><body>registry</body></html>"

    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content)
    html = await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/jobs", stage="registry")

    assert html == "<html><body>registry</body></html>"


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_retries_transient_failures(monkeypatch):
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
    from app.utils import anti_detection

    call_count = 0

    async def fake_fetch_page_content(url: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("navigation timeout")
        return "<html><body>detail</body></html>"

    async def no_wait(self, attempt: int) -> None:
        return None

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", no_wait)
    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content)

    html = await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/job/10108385", stage="detail_page")

    assert html == "<html><body>detail</body></html>"
    assert call_count == 2


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_rejects_interstitial_html():
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper

    async def fake_fetch_page_content(url: str) -> str:
        return "<html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>"

    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content)

    with pytest.raises(Exception, match=r"detail_page.*InterstitialChallenge.*10108385"):
        await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/job/10108385", stage="detail_page")


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_reuses_single_sync_browser_runtime():
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper

    call_log: list[str] = []
    scraper = CTGoodJobsBrowserPageScraper()

    def fake_start_sync_runtime():
        call_log.append("start")

    def fake_stop_sync_runtime():
        call_log.append("stop")

    def fake_fetch_page_content_sync(url: str) -> str:
        call_log.append(url)
        return "<html><body>ok</body></html>"

    scraper._start_sync_runtime = fake_start_sync_runtime
    scraper._stop_sync_runtime = fake_stop_sync_runtime
    scraper._fetch_page_content_sync = fake_fetch_page_content_sync

    async with scraper:
        first = await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/jobs", stage="registry")
        second = await scraper.fetch_page_html(
            "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
            stage="category_page",
        )

    assert first == "<html><body>ok</body></html>"
    assert second == "<html><body>ok</body></html>"
    assert call_log == [
        "start",
        "https://jobs.ctgoodjobs.hk/jobs",
        "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology",
        "stop",
    ]
