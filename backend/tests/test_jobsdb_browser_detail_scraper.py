from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper import jobsdb_browser_detail_scraper as jobsdb_browser_module
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.scraper.manual_action import ManualActionRequiredError
from app.services.crawl_cancellation_token import CrawlCancellationRequested


class _FakePage:
    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]
        self.navigation_timeout_ms: int | None = None

    def set_default_navigation_timeout(self, timeout_ms: int) -> None:
        self.navigation_timeout_ms = timeout_ms


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.contexts = [context]


class _FakeChromium:
    def __init__(
        self,
        browser: _FakeBrowser,
        *,
        connect_error: Exception | None = None,
    ) -> None:
        self.browser = browser
        self.connect_error = connect_error
        self.cdp_endpoints: list[str] = []

    def connect_over_cdp(self, endpoint: str) -> _FakeBrowser:
        self.cdp_endpoints.append(endpoint)
        if self.connect_error is not None:
            raise self.connect_error
        return self.browser


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    def stop(self) -> None:
        return None


class _FakeSyncPlaywright:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright

    def start(self) -> _FakePlaywright:
        return self.playwright


@pytest.mark.asyncio
async def test_jobsdb_reuse_browser_connects_via_configured_cdp_host(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _FakeContext()
    chromium = _FakeChromium(_FakeBrowser(context))
    fake_playwright = _FakePlaywright(chromium)
    registry = SimpleNamespace(get=lambda _profile: SimpleNamespace(debug_port=9333))

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(fake_playwright),
    )
    monkeypatch.setattr(
        jobsdb_browser_module,
        "get_live_browser_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        jobsdb_browser_module.settings,
        "manual_action_cdp_host",
        "127.0.0.2",
    )

    scraper = JobsDBBrowserDetailScraper(
        request_payload={
            "crawl_job_id": "crawl-jobsdb-reuse",
            "resume_strategy": "reuse_open_browser",
        },
        user_data_dir="C:/automation/jobsdb-profile",
        navigation_timeout_ms=4321,
    )

    with caplog.at_level("INFO", logger=jobsdb_browser_module.__name__):
        async with scraper:
            assert context.navigation_timeout_ms == 4321

    assert chromium.cdp_endpoints == ["http://127.0.0.2:9333"]
    success_record = next(
        record
        for record in caplog.records
        if record.message.startswith("manual_action_attach_success ")
    )
    success_message = success_record.getMessage()
    assert "crawl_job_id=crawl-jobsdb-reuse" in success_message
    assert "cdp_host=127.0.0.2" in success_message
    assert "cdp_connect_host=127.0.0.2" in success_message
    assert "debug_port=9333" in success_message


@pytest.mark.asyncio
async def test_jobsdb_reuse_browser_keeps_attach_failure_resumable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _FakeContext()
    chromium = _FakeChromium(
        _FakeBrowser(context),
        connect_error=ConnectionError("CDP endpoint unavailable"),
    )
    fake_playwright = _FakePlaywright(chromium)
    registry = SimpleNamespace(get=lambda _profile: SimpleNamespace(debug_port=9444))

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(fake_playwright),
    )
    monkeypatch.setattr(
        jobsdb_browser_module,
        "get_live_browser_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        jobsdb_browser_module.settings,
        "manual_action_cdp_host",
        "127.0.0.3",
    )

    scraper = JobsDBBrowserDetailScraper(
        request_payload={
            "crawl_job_id": "crawl-jobsdb-failed-attach",
            "resume_strategy": "reuse_open_browser",
        },
        user_data_dir="C:/automation/jobsdb-profile",
    )

    with caplog.at_level("INFO", logger=jobsdb_browser_module.__name__):
        with pytest.raises(ManualActionRequiredError) as raised:
            async with scraper:
                pass

    assert raised.value.stage == "reuse_open_browser_unavailable"
    assert chromium.cdp_endpoints == ["http://127.0.0.3:9444"]
    failure_record = next(
        record
        for record in caplog.records
        if record.message.startswith("manual_action_attach_failure ")
    )
    failure_message = failure_record.getMessage()
    assert "crawl_job_id=crawl-jobsdb-failed-attach" in failure_message
    assert "cdp_host=127.0.0.3" in failure_message
    assert "cdp_connect_host=127.0.0.3" in failure_message
    assert "debug_port=9444" in failure_message
    assert "error_type=ConnectionError" in failure_message


def test_jobsdb_cancellation_gate_runs_immediately_before_navigation() -> None:
    page = SimpleNamespace(
        goto_calls=0,
        goto=lambda *_args, **_kwargs: setattr(page, "goto_calls", page.goto_calls + 1),
    )

    class _CancelledToken:
        @staticmethod
        def raise_if_cancelled() -> None:
            raise CrawlCancellationRequested("cancelled")

    scraper = JobsDBBrowserDetailScraper(cancellation_token=_CancelledToken())
    scraper._runtime_started = True
    scraper._sync_page = page

    with pytest.raises(CrawlCancellationRequested):
        scraper._fetch_page_content_sync("https://hk.jobsdb.com/job/123")

    assert page.goto_calls == 0


def test_jobsdb_browser_settle_wait_checks_each_one_second_slice() -> None:
    waits: list[int] = []

    class _Token:
        checks = 0

        def raise_if_cancelled(self) -> None:
            self.checks += 1
            if self.checks == 2:
                raise CrawlCancellationRequested("cancelled")

    token = _Token()
    scraper = JobsDBBrowserDetailScraper(cancellation_token=token)
    scraper._sync_page = SimpleNamespace(wait_for_timeout=waits.append)

    with pytest.raises(CrawlCancellationRequested):
        scraper._wait_for_timeout_with_cancellation(3000)

    assert waits == [1000]
