from __future__ import annotations

import importlib
import sys
import types

import pytest

from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)


class _FakePage:
    def __init__(self, *, evaluate_results: list[object] | None = None) -> None:
        self.url = "about:blank"
        self.goto_calls: list[str] = []
        self.evaluate_calls: list[str] = []
        self.wait_for_timeout_calls: list[int] = []
        self.evaluate_results = list(evaluate_results or [])

    async def goto(self, url: str, **kwargs) -> None:
        self.url = url
        self.goto_calls.append(url)

    async def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append(script)
        if not self.evaluate_results:
            return None
        return self.evaluate_results.pop(0)

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_for_timeout_calls.append(timeout_ms)


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.pages = [page]
        self.default_navigation_timeout_ms: int | None = None
        self.closed = False

    async def new_page(self) -> _FakePage:
        self.pages.append(self._page)
        return self._page

    def set_default_navigation_timeout(self, timeout_ms: int) -> None:
        self.default_navigation_timeout_ms = timeout_ms

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.contexts = [context]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, *, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.connect_calls: list[str] = []
        self.launch_calls: list[dict[str, object]] = []

    async def connect_over_cdp(self, endpoint: str) -> _FakeBrowser:
        self.connect_calls.append(endpoint)
        return self.browser

    async def launch_persistent_context(self, user_data_dir: str, **kwargs) -> _FakeContext:
        self.launch_calls.append({"user_data_dir": user_data_dir, **kwargs})
        return self.browser.contexts[0]


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakePlaywrightManager:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> _FakePlaywright:
        return self.playwright


class _FakeRegistry:
    def __init__(self, session=None) -> None:
        self.session = session
        self.requested_paths: list[str] = []

    def get(self, browser_profile_path: str):
        self.requested_paths.append(browser_profile_path)
        return self.session


def _install_fake_async_playwright(monkeypatch: pytest.MonkeyPatch, chromium: _FakeChromium) -> None:
    async_api_module = types.ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: _FakePlaywrightManager(_FakePlaywright(chromium))
    playwright_module = types.ModuleType("playwright")
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)


@pytest.mark.asyncio
async def test_reuse_open_browser_requires_live_session(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    _install_fake_async_playwright(monkeypatch, chromium)
    monkeypatch.setattr(runtime_module, "get_live_browser_registry", lambda: _FakeRegistry(session=None))

    runtime = runtime_cls(
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        user_data_dir="C:/tmp/offertoday-profile",
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await runtime.start()

    assert "Fresh Profile" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reuse_open_browser_attaches_to_live_browser(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    _install_fake_async_playwright(monkeypatch, chromium)
    monkeypatch.setattr(
        runtime_module,
        "get_live_browser_registry",
        lambda: _FakeRegistry(session=types.SimpleNamespace(debug_port=9333)),
    )

    runtime = runtime_cls(
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        user_data_dir="C:/tmp/offertoday-profile",
        navigation_timeout_ms=45_000,
    )

    await runtime.start()
    try:
        assert chromium.connect_calls == ["http://127.0.0.1:9333"]
        assert context.default_navigation_timeout_ms == 45_000
        assert page.goto_calls == ["https://www.offertoday.com/hk/search"]
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_check_session_returns_listing_probe_results(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage(
        evaluate_results=[
            {
                "code": 0,
                "data": {
                    "resultList": [{"jobId": "jid-1"}],
                },
            }
        ]
    )
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    _install_fake_async_playwright(monkeypatch, chromium)
    monkeypatch.setattr(
        runtime_module,
        "get_live_browser_registry",
        lambda: _FakeRegistry(session=types.SimpleNamespace(debug_port=9444)),
    )

    runtime = runtime_cls(
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        user_data_dir="C:/tmp/offertoday-profile",
    )

    await runtime.start()
    try:
        result = await runtime.check_session(
            listing_payload={"keyword": "python", "page": 1, "pageSize": 1}
        )
    finally:
        await runtime.stop()

    assert result.current_url == "https://www.offertoday.com/hk/search"
    assert result.is_waf_challenge is False
    assert result.listing_probe_payload == {
        "code": 0,
        "data": {"resultList": [{"jobId": "jid-1"}]},
    }
    assert result.listing_result_count == 1
    assert page.evaluate_calls
