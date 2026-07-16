from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
from app.services.crawl_cancellation_token import CrawlCancellationRequested


def test_ctgoodjobs_cancellation_gate_runs_immediately_before_navigation() -> None:
    page = SimpleNamespace(
        goto_calls=0,
        goto=lambda *_args, **_kwargs: setattr(page, "goto_calls", page.goto_calls + 1),
    )

    class _CancelledToken:
        @staticmethod
        def raise_if_cancelled() -> None:
            raise CrawlCancellationRequested("cancelled")

    scraper = CTGoodJobsBrowserPageScraper(cancellation_token=_CancelledToken())
    scraper._runtime_started = True
    scraper._sync_page = page

    with pytest.raises(CrawlCancellationRequested):
        scraper._fetch_page_content_sync("https://www.ctgoodjobs.hk/job/123")

    assert page.goto_calls == 0


@pytest.mark.asyncio
async def test_ctgoodjobs_cancellation_is_not_wrapped_as_fetch_failure() -> None:
    class _CancelledToken:
        @staticmethod
        def raise_if_cancelled() -> None:
            raise CrawlCancellationRequested("cancelled")

        async def sleep(self, _seconds: float) -> None:
            raise AssertionError("cancellation must not enter retry backoff")

    scraper = CTGoodJobsBrowserPageScraper(
        page_content_fetcher=lambda _url: None,
        cancellation_token=_CancelledToken(),
    )

    with pytest.raises(CrawlCancellationRequested):
        await scraper.fetch_page_html(
            "https://www.ctgoodjobs.hk/job/123",
            stage="detail_page",
        )


@pytest.mark.asyncio
async def test_ctgoodjobs_paces_every_detail_retry_but_not_listing() -> None:
    calls = 0

    async def fetch(_url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("retry")
        return "<html><title>ordinary page</title></html>"

    class _Pacing:
        def __init__(self):
            self.calls = 0

        async def before_attempt(self):
            self.calls += 1

    class _Token:
        @staticmethod
        def raise_if_cancelled():
            return None

        @staticmethod
        async def sleep(_seconds):
            return None

    pacing = _Pacing()
    scraper = CTGoodJobsBrowserPageScraper(
        page_content_fetcher=fetch,
        cancellation_token=_Token(),
        detail_pacing_controller=pacing,
        max_attempts=2,
    )

    await scraper.fetch_page_html("https://example.test/detail", stage="detail_page")
    assert pacing.calls == 2

    calls = 1
    await scraper.fetch_page_html("https://example.test/listing", stage="category_page")
    assert pacing.calls == 2
