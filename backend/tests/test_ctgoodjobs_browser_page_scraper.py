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
async def test_ctgoodjobs_browser_page_scraper_retries_interstitial_html_before_succeeding(monkeypatch):
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
    from app.utils import anti_detection

    call_count = 0

    async def fake_fetch_page_content(url: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return "<html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>"
        return "<html><body>detail</body></html>"

    async def no_wait(self, attempt: int) -> None:
        return None

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", no_wait)
    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content, max_attempts=3)

    html = await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/job/10108385", stage="detail_page")

    assert html == "<html><body>detail</body></html>"
    assert call_count == 3


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_rejects_interstitial_html(monkeypatch):
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
    from app.scraper.manual_action import ManualActionRequiredError
    from app.utils import anti_detection

    call_count = 0

    async def fake_fetch_page_content(url: str) -> str:
        nonlocal call_count
        call_count += 1
        return "<html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>"

    async def no_wait(self, attempt: int) -> None:
        return None

    monkeypatch.setattr(anti_detection.ExponentialBackoff, "wait", no_wait)
    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content, max_attempts=3)

    with pytest.raises(ManualActionRequiredError, match=r"CTGoodJobs detail_page fetch blocked by human verification"):
        await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/job/10108385", stage="detail_page")

    assert call_count == 3


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_rejects_human_verification_interstitial():
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
    from app.scraper.manual_action import ManualActionRequiredError

    async def fake_fetch_page_content(url: str) -> str:
        return """
        <html>
          <body>
            <h1>Let's confirm you are human</h1>
            <p>Complete the security check before continuing.</p>
          </body>
        </html>
        """

    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content)

    with pytest.raises(ManualActionRequiredError, match=r"CTGoodJobs registry fetch blocked by human verification"):
        await scraper.fetch_page_html("https://jobs.ctgoodjobs.hk/jobs", stage="registry")


@pytest.mark.asyncio
async def test_ctgoodjobs_browser_page_scraper_raises_manual_action_required_for_human_verification():
    from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
    from app.scraper.manual_action import ManualActionRequiredError

    async def fake_fetch_page_content(url: str) -> str:
        return """
        <html>
          <body>
            <h1>Let's confirm you are human</h1>
            <p>Complete the security check before continuing.</p>
          </body>
        </html>
        """

    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=fake_fetch_page_content)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await scraper.fetch_page_html(
            "https://jobs.ctgoodjobs.hk/jobs",
            stage="registry",
        )

    exc = exc_info.value
    assert exc.source_site == "ctgoodjobs"
    assert exc.stage == "registry"
    assert exc.blocked_url == "https://jobs.ctgoodjobs.hk/jobs"
    assert exc.referer is None
    assert exc.resume_context == {}


@pytest.mark.asyncio
async def test_manual_action_required_error_to_payload_returns_defensive_copies():
    from app.scraper.manual_action import ManualActionRequiredError

    instructions = ["Open Edge using the listed profile."]
    resume_context = {"job_id": "crawl-123"}
    error = ManualActionRequiredError(
        source_site="ctgoodjobs",
        stage="registry",
        blocked_url="https://jobs.ctgoodjobs.hk/jobs",
        message="CTGoodJobs registry fetch blocked by human verification",
        instructions=instructions,
        resume_context=resume_context,
    )

    payload = error.to_payload(
        crawl_mode="headed",
        browser_channel="msedge",
        browser_profile_path="C:/profile",
    )

    assert payload["instructions"] == instructions
    assert payload["resume_context"] == resume_context
    assert payload["instructions"] is not instructions
    assert payload["resume_context"] is not resume_context


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
