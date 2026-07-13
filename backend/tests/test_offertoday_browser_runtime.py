from __future__ import annotations

from dataclasses import fields
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
)
from app.sources.offertoday.detail_identity import OfferTodayIdentityError
from app.sources.offertoday.listing_contract import (
    OfferTodayBrowserContextLostError,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
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
        result = self.evaluate_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

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
        self.fail_launch_by_channel: dict[str | None, Exception] = {}

    async def connect_over_cdp(self, endpoint: str) -> _FakeBrowser:
        self.connect_calls.append(endpoint)
        return self.browser

    async def launch_persistent_context(self, user_data_dir: str, **kwargs) -> _FakeContext:
        self.launch_calls.append({"user_data_dir": user_data_dir, **kwargs})
        channel = kwargs.get("channel")
        if channel in self.fail_launch_by_channel:
            raise self.fail_launch_by_channel[channel]
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


def _runtime_with_listing_envelope(
    runtime_module,
    *,
    payload: object,
    http_status: int = 200,
    response_url: str = OFFERTODAY_LISTING_SEARCH_URL,
):
    page = _FakePage(
        evaluate_results=[
            None,
            {
                "httpStatus": http_status,
                "responseUrl": response_url,
                "text": json.dumps(payload),
            },
        ]
    )
    page.url = "https://www.offertoday.com/hk/search"
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page
    return runtime, page


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
async def test_headed_fresh_profile_retries_missing_msedge_with_chromium(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    chromium.fail_launch_by_channel["msedge"] = RuntimeError(
        "BrowserType.launch_persistent_context: Chromium distribution 'msedge' is not found at /usr/bin/msedge"
    )
    _install_fake_async_playwright(monkeypatch, chromium)

    expected_user_data_dir = str(Path("C:/tmp/offertoday-profile").resolve())

    runtime = runtime_cls(
        resume_strategy="fresh_profile",
        user_data_dir="C:/tmp/offertoday-profile",
        browser_channel="msedge",
        navigation_timeout_ms=45_000,
    )

    await runtime.start()
    try:
        assert chromium.launch_calls == [
            {
                "user_data_dir": expected_user_data_dir,
                "headless": False,
                "channel": "msedge",
            },
            {
                "user_data_dir": expected_user_data_dir,
                "headless": False,
                "channel": "chromium",
            },
        ]
        assert context.default_navigation_timeout_ms == 45_000
        assert page.goto_calls == ["https://www.offertoday.com/hk/search"]
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_headed_fresh_profile_reports_display_unavailable_as_manual_action(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser=browser)
    fake_playwright = _install_fake_async_playwright(monkeypatch, chromium)

    async def fake_launch(*args, **kwargs):
        raise RuntimeError(
            "Unable to launch headed browser with channel 'chromium': "
            "BrowserType.launch_persistent_context: Target page, context or browser has been closed\n"
            "Looks like you launched a headed browser without having a XServer running.\n"
            "Missing X server or $DISPLAY"
        )

    monkeypatch.setattr(
        runtime_module,
        "launch_persistent_context_with_fallback_async",
        fake_launch,
    )

    runtime = runtime_cls(
        resume_strategy="fresh_profile",
        user_data_dir="C:/tmp/offertoday-profile",
        browser_channel="chromium",
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await runtime.start()

    assert exc_info.value.stage == "headed_display_unavailable"
    assert "X server" in str(exc_info.value)
    assert fake_playwright.stopped is True
    assert runtime._playwright is None
    assert runtime._context is None
    assert runtime._page is None
    assert runtime._runtime_started is False


@pytest.mark.asyncio
async def test_fetch_listing_json_delegates_to_allowed_endpoint(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    payload = {"keyword": "python", "page": 1}
    calls: list[tuple[str, str, object]] = []

    async def fake_fetch_json(url: str, *, method: str, payload=None):
        calls.append((url, method, payload))
        return {"code": 0, "data": {"resultList": []}}

    monkeypatch.setattr(runtime, "_fetch_json", fake_fetch_json)

    await runtime.fetch_listing_json(payload)
    await runtime.fetch_listing_json(
        payload,
        listing_url=OFFERTODAY_LISTING_BROWSE_URL,
    )

    assert calls == [
        (OFFERTODAY_LISTING_SEARCH_URL, "POST", payload),
        (OFFERTODAY_LISTING_BROWSE_URL, "POST", payload),
    ]


@pytest.mark.asyncio
async def test_fetch_listing_page_returns_typed_context_evidence_without_cursor_state(
    monkeypatch,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._context_id = "opaque-runtime-context"
    response = {"code": 0, "data": {"resultList": []}}

    async def fake_fetch_json_response(url, *, method, payload=None):
        assert url == OFFERTODAY_LISTING_SEARCH_URL
        assert method == "POST"
        return runtime_module._OfferTodayHttpJsonResponse(
            payload=response,
            http_status=200,
            response_url=url,
        )

    monkeypatch.setattr(runtime, "_fetch_json_response", fake_fetch_json_response)

    result = await runtime.fetch_listing_page(
        {"keyword": "python", "page": 1},
        listing_url=OFFERTODAY_LISTING_SEARCH_URL,
    )

    assert result.payload == response
    assert result.browser_context_hash == hashlib.sha256(
        b"opaque-runtime-context"
    ).hexdigest()
    assert result.http_status == 200
    assert result.response_url == OFFERTODAY_LISTING_SEARCH_URL
    assert not hasattr(runtime, "cursor")
    assert not hasattr(runtime, "session_id")


@pytest.mark.asyncio
async def test_fetch_listing_page_classifies_only_known_browser_context_loss(
    monkeypatch,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()

    async def lost_fetch(_url, *, method, payload=None):
        raise RuntimeError(
            "Target page, context or browser has been closed: private-profile-path"
        )

    monkeypatch.setattr(runtime, "_fetch_json_response", lost_fetch)

    with pytest.raises(OfferTodayBrowserContextLostError) as exc_info:
        await runtime.fetch_listing_page({"page": 2, "pageSize": 10})

    assert "private-profile-path" not in str(exc_info.value)

    async def programmer_error(_url, *, method, payload=None):
        raise RuntimeError("programmer error")

    monkeypatch.setattr(runtime, "_fetch_json_response", programmer_error)
    with pytest.raises(RuntimeError, match="programmer error"):
        await runtime.fetch_listing_page({"page": 1, "pageSize": 10})


@pytest.mark.asyncio
async def test_fetch_listing_json_rejects_unknown_endpoint_before_transport(
    monkeypatch,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    transport_calls = 0

    async def fake_fetch_json(*args, **kwargs):
        nonlocal transport_calls
        transport_calls += 1
        return {}

    monkeypatch.setattr(runtime, "_fetch_json", fake_fetch_json)

    with pytest.raises(ValueError, match="listing URL"):
        await runtime.fetch_listing_json(
            {"keyword": "python", "page": 1},
            listing_url="https://example.test/listing",
        )

    assert transport_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("listing_url", [[], {}])
async def test_fetch_listing_json_rejects_non_string_endpoint_before_transport(
    monkeypatch,
    listing_url,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    transport_calls = 0

    async def fake_fetch_json(*args, **kwargs):
        nonlocal transport_calls
        transport_calls += 1
        return {}

    monkeypatch.setattr(runtime, "_fetch_json", fake_fetch_json)

    with pytest.raises(ValueError, match="listing URL"):
        await runtime.fetch_listing_json(
            {"keyword": "python", "page": 1},
            listing_url=listing_url,
        )

    assert transport_calls == 0


@pytest.mark.asyncio
async def test_fetch_detail_json_uses_distinct_validated_identifiers(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    calls: list[tuple[str, str, object]] = []

    async def fake_fetch_json(url: str, *, method: str, payload=None):
        calls.append((url, method, payload))
        return {"code": 0, "data": {"jobId": "job-1"}}

    monkeypatch.setattr(runtime, "_fetch_json", fake_fetch_json)

    result = await runtime.fetch_detail_json(
        job_id="job-1",
        encrypted_job_id="encrypted-1",
    )

    assert result == {"code": 0, "data": {"jobId": "job-1"}}
    assert calls == [
        (
            "https://www.offertoday.com/wapi/geek/recommend/"
            "jobDetail?id=job-1&encryptJobId=encrypted-1",
            "GET",
            None,
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_id", "encrypted_job_id"),
    [
        (None, "encrypted-1"),
        ("", "encrypted-1"),
        ("   ", "encrypted-1"),
        (True, "encrypted-1"),
        ([], "encrypted-1"),
        ({}, "encrypted-1"),
        ("job-1", None),
        ("job-1", ""),
        ("job-1", "   "),
        ("job-1", False),
        ("job-1", []),
        ("job-1", {}),
    ],
)
async def test_fetch_detail_json_rejects_invalid_identifiers_before_transport(
    monkeypatch,
    job_id,
    encrypted_job_id,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    transport_calls = 0

    async def fake_fetch_json(*args, **kwargs):
        nonlocal transport_calls
        transport_calls += 1
        return {}

    monkeypatch.setattr(runtime, "_fetch_json", fake_fetch_json)

    with pytest.raises(OfferTodayIdentityError):
        await runtime.fetch_detail_json(
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
        )

    assert transport_calls == 0


@pytest.mark.asyncio
async def test_fetch_listing_json_preserves_authenticated_browser_request_evidence():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    payload = {"keyword": "python", "page": 1, "pageSize": 50}
    response_payload = {"code": 0, "data": {"resultList": []}}
    page = _FakePage(
        evaluate_results=[
            "csrf-123",
            {
                "httpStatus": 200,
                "responseUrl": OFFERTODAY_LISTING_BROWSE_URL,
                "text": json.dumps(response_payload),
            },
        ]
    )
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    result = await runtime.fetch_listing_json(
        payload,
        listing_url=OFFERTODAY_LISTING_BROWSE_URL,
    )

    assert result == response_payload
    assert "response.status" in page.evaluate_calls[1]
    assert "response.url" in page.evaluate_calls[1]
    assert "response.text()" in page.evaluate_calls[1]
    assert "response.json()" not in page.evaluate_calls[1]
    assert page.evaluate_arg_calls[1] == {
        "url": OFFERTODAY_LISTING_BROWSE_URL,
        "options": {
            "method": "POST",
            "headers": {
                **OFFERTODAY_COMMON_HEADERS,
                "csrf-token": "csrf-123",
            },
            "credentials": "include",
            "body": json.dumps(payload, ensure_ascii=True),
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [429, 503])
async def test_fetch_json_raises_typed_http_error_with_payload_evidence(
    monkeypatch,
    http_status,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {"code": 1002, "message": "Login expired"}
    page = _FakePage(
        evaluate_results=[
            {
                "httpStatus": http_status,
                "responseUrl": OFFERTODAY_LISTING_SEARCH_URL,
                "text": json.dumps(response_payload),
            }
        ]
    )
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    async def fake_read_csrf_token():
        return None

    monkeypatch.setattr(runtime, "_read_csrf_token", fake_read_csrf_token)

    with pytest.raises(OfferTodayTransportError) as exc_info:
        await runtime.fetch_listing_json({"keyword": "", "page": 1})

    error = exc_info.value
    assert error.error_kind == "http"
    assert error.http_status == http_status
    assert error.response_url == OFFERTODAY_LISTING_SEARCH_URL
    assert error.payload == response_payload
    classification = classify_offertoday_response(
        error.payload,
        operation="listing",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )
    assert classification.kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT


@pytest.mark.asyncio
async def test_fetch_json_uses_final_response_url_to_detect_waf_challenge(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    waf_url = "https://www.offertoday.com/web/passport/cm/verify?redirect=/hk/search"
    response_payload = {"code": 0, "data": {"resultList": []}}
    page = _FakePage(
        evaluate_results=[
            {
                "httpStatus": 200,
                "responseUrl": waf_url,
                "text": json.dumps(response_payload),
            }
        ]
    )
    page.url = "https://www.offertoday.com/hk/search"
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    async def fake_read_csrf_token():
        return None

    monkeypatch.setattr(runtime, "_read_csrf_token", fake_read_csrf_token)

    with pytest.raises(OfferTodayTransportError) as exc_info:
        await runtime.fetch_listing_json({"keyword": "", "page": 1})

    error = exc_info.value
    assert error.error_kind == "http"
    assert error.http_status == 200
    assert error.response_url == waf_url
    assert error.payload == response_payload
    classification = classify_offertoday_response(
        error.payload,
        operation="listing",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )
    assert classification.kind is OfferTodayResponseKind.WAF_CHALLENGE


@pytest.mark.asyncio
async def test_fetch_json_reports_http_200_non_json_as_invalid_payload(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_url = OFFERTODAY_LISTING_SEARCH_URL
    page = _FakePage(
        evaluate_results=[
            {
                "httpStatus": 200,
                "responseUrl": response_url,
                "text": "<html>not json</html>",
            }
        ]
    )
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    async def fake_read_csrf_token():
        return None

    monkeypatch.setattr(runtime, "_read_csrf_token", fake_read_csrf_token)

    with pytest.raises(OfferTodayTransportError) as exc_info:
        await runtime.fetch_listing_json({"keyword": "", "page": 1})

    error = exc_info.value
    assert error.error_kind == "invalid_json"
    assert error.http_status == 200
    assert error.response_url == response_url
    assert error.payload is None
    classification = classify_offertoday_response(
        error.payload,
        operation="listing",
        current_url=error.response_url,
        transport_error=error,
        http_status=error.http_status,
    )
    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD


@pytest.mark.asyncio
async def test_fetch_json_returns_none_for_non_object_json(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    page = _FakePage(
        evaluate_results=[
            {
                "httpStatus": 200,
                "responseUrl": OFFERTODAY_LISTING_SEARCH_URL,
                "text": "[]",
            }
        ]
    )
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    async def fake_read_csrf_token():
        return None

    monkeypatch.setattr(runtime, "_read_csrf_token", fake_read_csrf_token)

    result = await runtime.fetch_listing_json({"keyword": "", "page": 1})

    assert result is None
    classification = classify_offertoday_response(result, operation="listing")
    assert classification.kind is OfferTodayResponseKind.INVALID_PAYLOAD


@pytest.mark.asyncio
async def test_check_session_classifies_success_with_empty_result_list():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {"code": 0, "data": {"resultList": []}}
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
    )

    result = await runtime.check_session()

    assert [field.name for field in fields(result)] == [
        "current_url",
        "is_waf_challenge",
        "listing_probe_payload",
        "listing_result_count",
        "classification",
        "api_code",
        "message",
        "healthy",
    ]
    assert result.current_url == "https://www.offertoday.com/hk/search"
    assert result.is_waf_challenge is False
    assert result.listing_probe_payload == response_payload
    assert result.listing_result_count == 0
    assert result.classification is OfferTodayResponseKind.SUCCESS
    assert result.api_code == 0
    assert result.message is None
    assert result.healthy is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        (
            {"code": 1002, "message": "Login expired", "data": {"resultList": []}},
            OfferTodayResponseKind.AUTH_EXPIRED,
        ),
        (
            {"code": -1000035, "message": "IP blocked", "data": {"resultList": []}},
            OfferTodayResponseKind.IP_BLOCKED,
        ),
    ],
)
async def test_check_session_classifies_unhealthy_api_response(payload, expected_kind):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=payload,
    )

    result = await runtime.check_session()

    assert result.classification is expected_kind
    assert result.api_code == payload["code"]
    assert result.message == payload["message"]
    assert result.listing_probe_payload == payload
    assert result.listing_result_count == 0
    assert result.healthy is False


@pytest.mark.asyncio
async def test_check_session_classifies_waf_from_final_response_url():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    waf_url = "https://www.offertoday.com/web/passport/cm/verify?redirect=/hk/search"
    response_payload = {"code": 0, "data": {"resultList": []}}
    runtime, page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
        response_url=waf_url,
    )
    assert page.url == "https://www.offertoday.com/hk/search"

    result = await runtime.check_session()

    assert result.current_url == waf_url
    assert result.is_waf_challenge is True
    assert result.listing_probe_payload == response_payload
    assert result.classification is OfferTodayResponseKind.WAF_CHALLENGE
    assert result.api_code is None
    assert result.healthy is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [TimeoutError("listing timeout"), ConnectionError("browser disconnected")],
)
async def test_check_session_classifies_expected_transport_error(transport_error):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    page = _FakePage(evaluate_results=[transport_error])
    page.url = "https://www.offertoday.com/hk/search"
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    result = await runtime.check_session()

    assert result.current_url == page.url
    assert result.listing_probe_payload is None
    assert result.listing_result_count == 0
    assert result.classification is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert result.api_code is None
    assert str(transport_error) in str(result.message)
    assert result.healthy is False


@pytest.mark.asyncio
async def test_check_session_classifies_http_transport_evidence():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {"code": 1002, "message": "Login expired"}
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
        http_status=503,
    )

    result = await runtime.check_session()

    assert result.current_url == OFFERTODAY_LISTING_SEARCH_URL
    assert result.listing_probe_payload == response_payload
    assert result.classification is OfferTodayResponseKind.TRANSIENT_TRANSPORT
    assert result.api_code is None
    assert "503" in str(result.message)
    assert result.healthy is False


@pytest.mark.asyncio
async def test_check_session_does_not_swallow_programmer_or_filesystem_error():
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    error = FileNotFoundError("missing browser profile")
    page = _FakePage(evaluate_results=[error])
    runtime = runtime_module.OfferTodayBrowserRuntime()
    runtime._page = page

    with pytest.raises(FileNotFoundError) as exc_info:
        await runtime.check_session()

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_require_healthy_session_returns_healthy_result(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()
    expected = SimpleNamespace(
        current_url="https://www.offertoday.com/hk/search",
        is_waf_challenge=False,
        listing_probe_payload={"code": 0, "data": {"resultList": []}},
        listing_result_count=0,
        classification=OfferTodayResponseKind.SUCCESS,
        api_code=0,
        message=None,
        healthy=True,
    )

    async def fake_check_session(*, listing_payload=None):
        return expected

    monkeypatch.setattr(runtime, "check_session", fake_check_session)

    result = await runtime.require_healthy_session(
        listing_payload={"keyword": "python", "page": 1}
    )

    assert result is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("classification", "api_code", "blocked_url"),
    [
        (
            OfferTodayResponseKind.AUTH_EXPIRED,
            1002,
            "https://www.offertoday.com/hk/search",
        ),
        (
            OfferTodayResponseKind.WAF_CHALLENGE,
            None,
            "https://www.offertoday.com/web/passport/cm/verify",
        ),
        (
            OfferTodayResponseKind.IP_BLOCKED,
            -1000035,
            OFFERTODAY_LISTING_SEARCH_URL,
        ),
    ],
)
async def test_require_healthy_session_raises_evidence_rich_manual_action(
    monkeypatch,
    classification,
    api_code,
    blocked_url,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()

    async def fake_check_session(*, listing_payload=None):
        return SimpleNamespace(
            current_url=blocked_url,
            is_waf_challenge=(classification is OfferTodayResponseKind.WAF_CHALLENGE),
            listing_probe_payload={"code": api_code, "message": "blocked"},
            listing_result_count=0,
            classification=classification,
            api_code=api_code,
            message="blocked",
            healthy=False,
        )

    monkeypatch.setattr(runtime, "check_session", fake_check_session)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await runtime.require_healthy_session()

    error = exc_info.value
    assert error.source_site == "offertoday"
    assert error.stage == "browser_session"
    assert error.blocked_url == blocked_url
    assert classification.value in error.message
    assert error.instructions
    assert error.resume_context == {
        "classification": classification.value,
        "api_code": api_code,
        "message": "blocked",
    }


@pytest.mark.asyncio
async def test_require_healthy_session_raises_runtime_error_for_other_failure(
    monkeypatch,
):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime = runtime_module.OfferTodayBrowserRuntime()

    async def fake_check_session(*, listing_payload=None):
        return SimpleNamespace(
            current_url="https://www.offertoday.com/hk/search",
            is_waf_challenge=False,
            listing_probe_payload={"code": 99, "message": "unexpected"},
            listing_result_count=0,
            classification=OfferTodayResponseKind.INVALID_PAYLOAD,
            api_code=99,
            message="unexpected",
            healthy=False,
        )

    monkeypatch.setattr(runtime, "check_session", fake_check_session)

    with pytest.raises(RuntimeError, match="invalid_payload.*99"):
        await runtime.require_healthy_session()


@pytest.mark.asyncio
async def test_run_smoke_test_skips_detail_when_session_is_unhealthy(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {
        "code": 1002,
        "message": "Login expired",
        "data": {
            "resultList": [
                {"jobId": "job-1", "encryptJobId": "encrypted-1"},
            ]
        },
    }
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
    )
    detail_calls = 0

    async def fake_fetch_detail_json(**kwargs):
        nonlocal detail_calls
        detail_calls += 1
        return {"code": 0, "data": {"jobId": kwargs["job_id"]}}

    monkeypatch.setattr(runtime, "fetch_detail_json", fake_fetch_detail_json)

    result = await runtime.run_smoke_test(detail_limit=1)

    assert result["listing_ok"] is False
    assert result["classification"] == OfferTodayResponseKind.AUTH_EXPIRED.value
    assert result["api_code"] == 1002
    assert result["detail_results"] == []
    assert detail_calls == 0


@pytest.mark.asyncio
async def test_run_smoke_test_resolves_explicit_and_jobid_fallback_rows(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {
        "code": 0,
        "data": {
            "resultList": [
                {"jobId": "job-1", "encryptJobId": "encrypted-1"},
                {"jobId": "job-2"},
                {"jobId": "job-3", "encryptJobId": ""},
                {"jobId": True, "encryptJobId": "encrypted-4"},
                {"jobId": "job-5", "encryptJobId": []},
                {"jobId": "job-6", "encryptJobId": "encrypted-6"},
            ]
        },
    }
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
    )
    detail_calls: list[tuple[str, str | None]] = []

    async def fake_fetch_detail_json(*, job_id, encrypted_job_id=None):
        detail_calls.append((job_id, encrypted_job_id))
        return {"code": 0, "data": {"jobId": job_id}}

    monkeypatch.setattr(runtime, "fetch_detail_json", fake_fetch_detail_json)

    result = await runtime.run_smoke_test(detail_limit=6)

    assert result["listing_ok"] is True
    assert result["classification"] == OfferTodayResponseKind.SUCCESS.value
    assert result["api_code"] == 0
    assert detail_calls == [
        ("job-1", "encrypted-1"),
        ("job-2", "job-2"),
        ("job-3", "job-3"),
        ("job-6", "encrypted-6"),
    ]
    assert result["detail_results"] == [
        {"job_id": "job-1", "code": 0},
        {"job_id": "job-2", "code": 0},
        {"job_id": "job-3", "code": 0},
        {"job_id": "job-6", "code": 0},
    ]


@pytest.mark.asyncio
async def test_run_smoke_test_applies_detail_limit_after_identity_validation(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    response_payload = {
        "code": 0,
        "data": {
            "resultList": [
                {"jobId": "missing-encrypted-id"},
                {"jobId": "job-2", "encryptJobId": "encrypted-2"},
                {"jobId": "job-3", "encryptJobId": "encrypted-3"},
            ]
        },
    }
    runtime, _page = _runtime_with_listing_envelope(
        runtime_module,
        payload=response_payload,
    )
    detail_calls: list[tuple[str, str | None]] = []

    async def fake_fetch_detail_json(*, job_id, encrypted_job_id=None):
        detail_calls.append((job_id, encrypted_job_id))
        return {"code": 0, "data": {"jobId": job_id}}

    monkeypatch.setattr(runtime, "fetch_detail_json", fake_fetch_detail_json)

    result = await runtime.run_smoke_test(detail_limit=1)

    assert detail_calls == [("missing-encrypted-id", "missing-encrypted-id")]
    assert result["detail_results"] == [
        {"job_id": "missing-encrypted-id", "code": 0}
    ]


@pytest.mark.asyncio
async def test_check_session_returns_listing_probe_results(monkeypatch):
    runtime_module = importlib.import_module("app.scraper.offertoday_browser_runtime")
    runtime_cls = getattr(runtime_module, "OfferTodayBrowserRuntime")

    page = _FakePage(
        evaluate_results=[
            "csrf-123",
            {
                "httpStatus": 200,
                "responseUrl": OFFERTODAY_LISTING_SEARCH_URL,
                "text": json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "resultList": [{"jobId": "jid-1"}],
                        },
                    }
                ),
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
                "httpStatus": 200,
                "responseUrl": OFFERTODAY_LISTING_SEARCH_URL,
                "text": json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "resultList": [],
                        },
                    }
                ),
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
            classification=OfferTodayResponseKind.SUCCESS,
            api_code=0,
            message=None,
            healthy=True,
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
    identity_module = importlib.import_module("app.sources.offertoday.detail_identity")
    policy_module = importlib.import_module("app.sources.offertoday.response_policy")

    job = SimpleNamespace(
        source_site="offertoday", source_job_id="jid-1", job_id="jid-1", description=""
    )
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

        def resolve_detail_identity(self, _job, listing):
            captured["resolved_listing"] = listing
            return identity_module.OfferTodayDetailIdentity(
                job_id="jid-1",
                encrypted_job_id="enc-jid-1",
                encrypted_job_id_source="encryptJobId",
            )

        def repair_job_with_detail_result(self, _job, detail_result):
            captured["detail_result"] = detail_result
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

        async def fetch_job_detail(
            self,
            job_id: str,
            *,
            encrypted_job_id: str | None = None,
            encrypted_job_id_source: str | None = None,
        ):
            captured["fetch_call"] = (
                job_id,
                encrypted_job_id,
                encrypted_job_id_source,
            )
            raw_response = {"code": 0, "data": {"jobId": job_id}}
            detail_result = identity_module.OfferTodayDetailFetchResult(
                identity=identity_module.OfferTodayDetailIdentity(
                    job_id=job_id,
                    encrypted_job_id=encrypted_job_id,
                    encrypted_job_id_source=encrypted_job_id_source,
                ),
                classification=policy_module.classify_offertoday_response(
                    raw_response,
                    operation="detail",
                    expected_job_id=job_id,
                ),
                raw_response=raw_response,
                parsed_detail={"job_id": job_id, "encrypted_job_id": ""},
                canonical_detail={
                    "job_id": job_id,
                    "encrypted_job_id": encrypted_job_id,
                    "encrypted_job_id_source": encrypted_job_id_source,
                },
            )
            captured["scraper_detail_result"] = detail_result
            return detail_result

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
    assert captured["fetch_call"] == (
        "jid-1",
        "enc-jid-1",
        "encryptJobId",
    )
    assert captured["detail_result"] is captured["scraper_detail_result"]
    assert result["live_repaired_descriptions"] == 1


@pytest.mark.asyncio
async def test_repair_jobs_records_terminal_detail_without_generic_failure_and_continues(
    monkeypatch,
):
    repair_module = importlib.import_module("backend.scripts.repair_offertoday_jobs")
    identity_module = importlib.import_module("app.sources.offertoday.detail_identity")
    policy_module = importlib.import_module("app.sources.offertoday.response_policy")

    jobs = [
        SimpleNamespace(
            source_site="offertoday",
            source_job_id="jid-terminal",
            job_id="jid-terminal",
            description="",
        ),
        SimpleNamespace(
            source_site="offertoday",
            source_job_id="jid-success",
            job_id="jid-success",
            description="",
        ),
    ]
    listings = {
        job.source_job_id: SimpleNamespace(
            detail_status="pending",
            detail_payload=None,
            detail_error_message=None,
            detail_completed_at=None,
        )
        for job in jobs
    }
    fetch_calls: list[tuple[str, str, str]] = []
    consumed_results: list[object] = []

    class _FakeSession:
        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _FakeService:
        def __init__(self, db) -> None:
            self.db = db

        def iter_repair_candidates(self, *, limit: int | None = None):
            return jobs

        def repair_job(self, _job):
            return SimpleNamespace(
                description_repaired=False,
                company_reassigned=False,
                listing_attached=False,
                action="unchanged",
            )

        def is_degraded_job(self, _job) -> bool:
            return not bool(_job.description)

        def get_latest_listing(self, source_job_id: str):
            return listings[source_job_id]

        def resolve_detail_identity(self, _job, _listing):
            if _job.source_job_id == "jid-terminal":
                return identity_module.OfferTodayDetailIdentity(
                    job_id=_job.source_job_id,
                    encrypted_job_id=_job.source_job_id,
                    encrypted_job_id_source="jobId_fallback",
                )
            return identity_module.OfferTodayDetailIdentity(
                job_id=_job.source_job_id,
                encrypted_job_id=f"enc-{_job.source_job_id}",
                encrypted_job_id_source="encryptJobId",
            )

        def repair_job_with_detail_result(self, target_job, detail_result):
            consumed_results.append(detail_result)
            target_listing = listings[target_job.source_job_id]
            if (
                detail_result.classification.kind
                is OfferTodayResponseKind.TERMINAL_UNAVAILABLE
            ):
                target_listing.detail_status = "terminal_unavailable"
                target_listing.detail_payload = detail_result.raw_response
                target_listing.detail_error_message = "terminal_unavailable:2520"
                target_listing.detail_completed_at = object()
                return SimpleNamespace(
                    description_repaired=False,
                    company_reassigned=False,
                    listing_attached=False,
                    action="terminal_unavailable",
                )

            target_job.description = "repaired"
            return SimpleNamespace(
                description_repaired=True,
                company_reassigned=False,
                listing_attached=False,
                action="updated",
            )

    class _FakeScraper:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(
            self,
            job_id: str,
            *,
            encrypted_job_id: str | None = None,
            encrypted_job_id_source: str | None = None,
        ):
            fetch_calls.append(
                (job_id, encrypted_job_id, encrypted_job_id_source)
            )
            if job_id == "jid-terminal":
                raw_response = {
                    "code": 2520,
                    "msg": "job unavailable",
                    "data": None,
                }
                parsed_detail = None
                canonical_detail = None
            else:
                raw_response = {"code": 0, "data": {"jobId": job_id}}
                parsed_detail = {"job_id": job_id}
                canonical_detail = {
                    "job_id": job_id,
                    "encrypted_job_id": encrypted_job_id,
                    "encrypted_job_id_source": encrypted_job_id_source,
                }
            return identity_module.OfferTodayDetailFetchResult(
                identity=identity_module.OfferTodayDetailIdentity(
                    job_id=job_id,
                    encrypted_job_id=encrypted_job_id,
                    encrypted_job_id_source=encrypted_job_id_source,
                ),
                classification=policy_module.classify_offertoday_response(
                    raw_response,
                    operation="detail",
                    expected_job_id=job_id,
                ),
                raw_response=raw_response,
                parsed_detail=parsed_detail,
                canonical_detail=canonical_detail,
            )

    monkeypatch.setattr(repair_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(repair_module, "OfferTodayJobRepairService", _FakeService)
    monkeypatch.setattr(repair_module, "OfferTodayBrowserDetailScraper", _FakeScraper)

    result = await repair_module.repair_jobs(
        execute=False,
        live_fetch_missing=True,
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    )

    terminal_listing = listings["jid-terminal"]
    assert fetch_calls == [
        ("jid-terminal", "jid-terminal", "jobId_fallback"),
        ("jid-success", "enc-jid-success", "encryptJobId"),
    ]
    assert len(consumed_results) == 2
    assert all(
        isinstance(result, identity_module.OfferTodayDetailFetchResult)
        for result in consumed_results
    )
    assert terminal_listing.detail_status == "terminal_unavailable"
    assert terminal_listing.detail_payload == {
        "code": 2520,
        "msg": "job unavailable",
        "data": None,
    }
    assert "2520" in str(terminal_listing.detail_error_message)
    assert result["live_terminal_unavailable"] == 1
    assert result["live_fetch_failed"] == 0
    assert result["live_repaired_descriptions"] == 1


@pytest.mark.asyncio
async def test_repair_jobs_rolls_back_and_propagates_manual_action_preflight(
    monkeypatch,
):
    repair_module = importlib.import_module("backend.scripts.repair_offertoday_jobs")
    expected_error = ManualActionRequiredError(
        source_site="offertoday",
        stage="browser_session",
        blocked_url="https://www.offertoday.com/hk/search",
        message="OfferToday login expired",
    )
    job = SimpleNamespace(
        source_site="offertoday",
        source_job_id="jid-1",
        job_id="jid-1",
        description="",
    )
    session_state = {"rollbacks": 0, "closed": 0}
    fetch_calls = 0

    class _FakeSession:
        def rollback(self) -> None:
            session_state["rollbacks"] += 1

        def close(self) -> None:
            session_state["closed"] += 1

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

    class _FakeScraper:
        def __init__(self, **kwargs) -> None:
            self.kwargs = dict(kwargs)

        async def __aenter__(self):
            raise expected_error

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_job_detail(self, *args, **kwargs):
            nonlocal fetch_calls
            fetch_calls += 1
            raise AssertionError("preflight failure must prevent detail fetch")

    monkeypatch.setattr(repair_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(repair_module, "OfferTodayJobRepairService", _FakeService)
    monkeypatch.setattr(repair_module, "OfferTodayBrowserDetailScraper", _FakeScraper)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        await repair_module.repair_jobs(
            execute=True,
            live_fetch_missing=True,
        )

    assert exc_info.value is expected_error
    assert session_state == {"rollbacks": 1, "closed": 1}
    assert fetch_calls == 0
