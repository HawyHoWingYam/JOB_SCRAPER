from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)


class _FakePage:
    def __init__(
        self,
        *,
        evaluate_results: list[object] | None = None,
        goto_error: Exception | None = None,
    ) -> None:
        self.url = "about:blank"
        self.goto_calls: list[str] = []
        self.evaluate_calls: list[str] = []
        self.evaluate_arg_calls: list[object] = []
        self.wait_for_timeout_calls: list[int] = []
        self.evaluate_results = list(evaluate_results or [])
        self.goto_error = goto_error

    async def goto(self, url: str, **kwargs) -> None:
        if self.goto_error is not None:
            raise self.goto_error
        self.url = url
        self.goto_calls.append(url)

    async def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append(script)
        self.evaluate_arg_calls.append(arg)
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


def _install_fake_async_playwright(
    monkeypatch: pytest.MonkeyPatch,
    chromium: _FakeChromium,
) -> _FakePlaywright:
    async_api_module = types.ModuleType("playwright.async_api")
    fake_playwright = _FakePlaywright(chromium)
    async_api_module.async_playwright = lambda: _FakePlaywrightManager(fake_playwright)
    playwright_module = types.ModuleType("playwright")
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)
    return fake_playwright


@pytest.mark.asyncio
async def test_reuse_open_browser_requires_live_session(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    fake_playwright = _install_fake_async_playwright(monkeypatch, chromium)
    monkeypatch.setattr(runtime_module, "get_live_browser_registry", lambda: _FakeRegistry(session=None))

    runtime = runtime_cls(
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        user_data_dir="C:/tmp/offertoday-profile",
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await runtime.start()

    assert "Fresh Profile" in str(exc_info.value)
    assert fake_playwright.stopped is True
    assert runtime._playwright is None
    assert runtime._context is None
    assert runtime._page is None
    assert runtime._runtime_started is False


@pytest.mark.asyncio
async def test_start_cleans_up_when_warmup_fails_after_fresh_profile_launch(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage(goto_error=RuntimeError("warmup failed"))
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    fake_playwright = _install_fake_async_playwright(monkeypatch, chromium)

    runtime = runtime_cls(
        user_data_dir="C:/tmp/offertoday-profile",
        navigation_timeout_ms=45_000,
    )

    with pytest.raises(RuntimeError, match="warmup failed"):
        await runtime.start()

    assert context.closed is True
    assert fake_playwright.stopped is True
    assert runtime._playwright is None
    assert runtime._context is None
    assert runtime._page is None
    assert runtime._runtime_started is False


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
            "csrf-123",
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


@pytest.mark.asyncio
async def test_fetch_listing_json_adds_csrf_token_header_from_cookie(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage(
        evaluate_results=[
            "csrf-123",
            {
                "code": 0,
                "data": {
                    "resultList": [],
                },
            },
        ]
    )
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    _install_fake_async_playwright(monkeypatch, chromium)
    monkeypatch.setattr(
        runtime_module,
        "get_live_browser_registry",
        lambda: _FakeRegistry(session=types.SimpleNamespace(debug_port=9555)),
    )

    runtime = runtime_cls(
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        user_data_dir="C:/tmp/offertoday-profile",
    )

    await runtime.start()
    try:
        result = await runtime.fetch_listing_json({"keyword": "", "page": 1, "pageSize": 1})
    finally:
        await runtime.stop()

    assert result == {
        "code": 0,
        "data": {
            "resultList": [],
        },
    }
    assert page.evaluate_arg_calls[1]["options"]["headers"]["csrf-token"] == "csrf-123"


@pytest.mark.asyncio
async def test_run_smoke_test_reports_detail_codes():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    runtime = runtime_cls()

    async def fake_check_session(*, listing_payload: dict[str, object] | None = None):
        return SimpleNamespace(
            current_url="https://www.offertoday.com/hk/search",
            is_waf_challenge=False,
            listing_probe_payload={
                "data": {
                    "resultList": [
                        {"jobId": "job-1", "encryptJobId": "job-1"},
                        {"jobId": "job-2", "encryptJobId": "job-2"},
                    ]
                }
            },
            listing_result_count=2,
        )

    async def fake_fetch_detail_json(*, job_id: str, encrypted_job_id: str | None = None):
        if job_id == "job-2":
            return {"code": -1000035, "data": {}}
        return {"code": 0, "data": {"jobId": job_id}}

    runtime.check_session = fake_check_session
    runtime.fetch_detail_json = fake_fetch_detail_json

    result = await runtime.run_smoke_test(
        listing_payload={"keyword": "data", "page": 1, "pageSize": 1},
        detail_limit=2,
    )

    assert result["listing_ok"] is True
    assert result["listing_count"] == 2
    assert result["detail_results"] == [
        {"job_id": "job-1", "code": 0},
        {"job_id": "job-2", "code": -1000035},
    ]


def test_build_probe_listing_payload_flattens_empty_keyword_sequence():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")

    payload = crawl_module._build_probe_listing_payload(category_ids=[], keywords=[])

    assert payload["keyword"] == ""


@pytest.mark.asyncio
async def test_repair_jobs_passes_resume_strategy_to_browser_scraper(monkeypatch):
    repair_module = importlib.import_module("backend.scripts.repair_offertoday_jobs")

    job = SimpleNamespace(source_site="offertoday", source_job_id="jid-1", job_id="jid-1", description="")
    captured: dict[str, object] = {}

    class _FakeSession:
        def commit(self) -> None:
            captured["committed"] = True

        def rollback(self) -> None:
            captured["rolled_back"] = True

        def close(self) -> None:
            captured["closed"] = True

    class _FakeService:
        def __init__(self, db) -> None:
            self.db = db

        def iter_repair_candidates(self, *, limit: int | None = None):
            return [job]

        def repair_job(self, _job):
            return SimpleNamespace(
                description_repaired=False,
                company_reassigned=False,
                listing_attached=False,
                action="unchanged",
            )

        def is_degraded_job(self, _job) -> bool:
            return True

        def get_latest_listing(self, source_job_id: str):
            captured["latest_listing_for"] = source_job_id
            return None

        def resolve_detail_identifiers(self, _job, listing):
            captured["resolved_listing"] = listing
            return ("jid-1", "enc-jid-1")

        def repair_job_with_detail_payload(self, _job, detail_payload):
            captured["detail_payload"] = detail_payload
            return SimpleNamespace(
                description_repaired=True,
                company_reassigned=False,
                listing_attached=False,
                action="updated",
            )

    class _FakeScraper:
        def __init__(self, **kwargs) -> None:
            captured["scraper_kwargs"] = dict(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(self, job_id: str, *, encrypted_job_id: str | None = None):
            captured["fetch_call"] = (job_id, encrypted_job_id)
            return {"jobId": job_id, "jobDesc": "<p>detail</p>"}

    monkeypatch.setattr(repair_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(repair_module, "OfferTodayJobRepairService", _FakeService)
    monkeypatch.setattr(repair_module, "OfferTodayBrowserDetailScraper", _FakeScraper)

    result = await repair_module.repair_jobs(
        execute=False,
        live_fetch_missing=True,
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    )

    assert captured["scraper_kwargs"]["request_payload"] == {
        "resume_strategy": RESUME_STRATEGY_REUSE_OPEN_BROWSER
    }
    assert captured["fetch_call"] == ("jid-1", "enc-jid-1")
    assert result["live_repaired_descriptions"] == 1


@pytest.mark.asyncio
async def test_repair_jobs_marks_listing_failed_for_unavailable_detail(monkeypatch):
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    unavailable_error_cls = getattr(scraper_module, "OfferTodayDetailUnavailableError", None)
    assert unavailable_error_cls is not None

    repair_module = importlib.import_module("backend.scripts.repair_offertoday_jobs")

    job = SimpleNamespace(source_site="offertoday", source_job_id="jid-1", job_id="jid-1", description="")
    listing = SimpleNamespace(
        detail_status="pending",
        detail_error_message=None,
        detail_completed_at=None,
    )

    class _FakeSession:
        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _FakeService:
        def __init__(self, db) -> None:
            self.db = db

        def iter_repair_candidates(self, *, limit: int | None = None):
            return [job]

        def repair_job(self, _job):
            return SimpleNamespace(
                description_repaired=False,
                company_reassigned=False,
                listing_attached=False,
                action="unchanged",
            )

        def is_degraded_job(self, _job) -> bool:
            return True

        def get_latest_listing(self, source_job_id: str):
            assert source_job_id == "jid-1"
            return listing

        def resolve_detail_identifiers(self, _job, _listing):
            return ("jid-1", "enc-jid-1")

    class _FakeScraper:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(self, job_id: str, *, encrypted_job_id: str | None = None):
            raise unavailable_error_cls(job_id=job_id, code=2520, message="job unavailable")

    monkeypatch.setattr(repair_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(repair_module, "OfferTodayJobRepairService", _FakeService)
    monkeypatch.setattr(repair_module, "OfferTodayBrowserDetailScraper", _FakeScraper)

    result = await repair_module.repair_jobs(
        execute=False,
        live_fetch_missing=True,
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    )

    assert listing.detail_status == "failed"
    assert "2520" in str(listing.detail_error_message)
    assert result["live_fetch_failed"] == 1
