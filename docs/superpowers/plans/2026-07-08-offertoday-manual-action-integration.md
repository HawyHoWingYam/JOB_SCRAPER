# OfferToday Manual-Action Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate OfferToday into the repo's reusable-browser and manual-action runtime so crawl and detail recovery can use a dedicated profile, reuse an open browser over CDP, and run explicit setup/check/smoke flows instead of depending only on `storage_state`.

**Architecture:** Add one shared async OfferToday browser runtime that owns browser launch, CDP attach, warmup, listing/detail fetches, and session health probes. Then route both `offertoday_standalone_crawl.py` and `OfferTodayBrowserDetailScraper` through that runtime, with OfferToday-specific config and operational scripts layered on top.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Playwright async API, pytest

---

## File Structure

**Create**
- `backend/app/scraper/offertoday_browser_runtime.py` — shared async runtime for OfferToday browser launch, CDP attach, listing/detail fetches, WAF detection, and check/smoke helpers
- `backend/tests/test_offertoday_browser_runtime.py` — focused runtime tests for resume strategy, live-browser attach behavior, and health checks

**Modify**
- `backend/app/config.py` — add OfferToday-specific browser settings and validator coverage
- `backend/app/scraper/offertoday_browser_detail_scraper.py` — delegate runtime creation and resume-strategy handling to the shared runtime
- `backend/scripts/offertoday_standalone_crawl.py` — replace ad hoc Playwright/session wiring with the shared runtime and add `--resume-strategy`, `--check`, and `--smoke-test`
- `backend/scripts/offertoday_auth_setup.py` — shift from storage-state-only setup to profile-first setup with optional live-session registration
- `backend/scripts/offertoday_transport_bakeoff.py` — compare fresh profile, `storage_state`, and CDP attach using the shared runtime helpers
- `backend/app/api/crawl_jobs.py` — pass OfferToday runtime arguments into the subprocess command consistently
- `backend/tests/test_offertoday_canonical_and_identity.py` — add detail-scraper tests for runtime selection and manual-action propagation
- `backend/tests/test_crawl_job_regressions.py` — add subprocess and resume-strategy regressions for OfferToday

### Task 1: Add OfferToday browser config and shared runtime

**Files:**
- Create: `backend/app/scraper/offertoday_browser_runtime.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_offertoday_browser_runtime.py`

- [ ] **Step 1: Write the failing runtime tests**

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)


class _FakePage:
    def __init__(self, *, url: str = "https://www.offertoday.com/hk/search", evaluate_result=None):
        self.url = url
        self._evaluate_result = evaluate_result or {"code": 0, "data": {"resultList": []}}

    async def goto(self, url, wait_until="domcontentloaded", timeout=30_000):
        self.url = url

    async def evaluate(self, js):
        return self._evaluate_result

    async def wait_for_url(self, matcher, timeout):
        self.url = "https://www.offertoday.com/hk/search"


class _FakeContext:
    def __init__(self, page: _FakePage):
        self.pages = [page]
        self._page = page
        self.default_navigation_timeout = None

    async def new_page(self):
        return self._page

    def set_default_navigation_timeout(self, timeout_ms):
        self.default_navigation_timeout = timeout_ms

    async def close(self):
        return None


class _FakeBrowser:
    def __init__(self, context: _FakeContext):
        self.contexts = [context]

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_runtime_raises_manual_action_when_reuse_browser_session_missing(monkeypatch):
    from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime

    runtime = OfferTodayBrowserRuntime(
        headed=True,
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        browser_profile_path="C:\\temp\\offertoday-profile",
    )

    monkeypatch.setattr(
        "app.scraper.offertoday_browser_runtime.get_live_browser_registry",
        lambda: SimpleNamespace(get=lambda _path: None),
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        async with runtime:
            pass

    assert exc_info.value.source_site == "offertoday"
    assert exc_info.value.stage == "reuse_open_browser_unavailable"


@pytest.mark.asyncio
async def test_runtime_attaches_to_live_browser_when_reuse_strategy_selected(monkeypatch):
    from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime

    observed = {}
    fake_page = _FakePage()
    fake_context = _FakeContext(fake_page)
    fake_browser = _FakeBrowser(fake_context)

    class _FakeChromium:
        async def connect_over_cdp(self, endpoint):
            observed["endpoint"] = endpoint
            return fake_browser

    class _FakePlaywright:
        chromium = _FakeChromium()

        async def stop(self):
            return None

    async def fake_start():
        return _FakePlaywright()

    monkeypatch.setattr(
        "app.scraper.offertoday_browser_runtime.async_playwright",
        lambda: SimpleNamespace(start=fake_start),
    )
    monkeypatch.setattr(
        "app.scraper.offertoday_browser_runtime.get_live_browser_registry",
        lambda: SimpleNamespace(
            get=lambda _path: SimpleNamespace(debug_port=9333, browser_profile_path="C:\\temp\\offertoday-profile")
        ),
    )

    runtime = OfferTodayBrowserRuntime(
        headed=True,
        resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER,
        browser_profile_path="C:\\temp\\offertoday-profile",
    )

    async with runtime:
        pass

    assert observed["endpoint"] == "http://127.0.0.1:9333"


@pytest.mark.asyncio
async def test_runtime_check_session_returns_listing_probe_result(monkeypatch):
    from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime

    fake_page = _FakePage(
        evaluate_result={"code": 0, "data": {"resultList": [{"jobId": "job-1"}]}}
    )

    runtime = OfferTodayBrowserRuntime(
        detail_json_fetcher=None,
        headed=False,
        resume_strategy=RESUME_STRATEGY_FRESH_PROFILE,
    )
    runtime._page = fake_page

    result = await runtime.check_session(category_ids=[112000], keyword="data")

    assert result.ok is True
    assert result.listing_count == 1
```

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run: `python -m pytest -q backend/tests/test_offertoday_browser_runtime.py`
Expected: FAIL with `ModuleNotFoundError` for `app.scraper.offertoday_browser_runtime` or missing attributes such as `check_session`.

- [ ] **Step 3: Add OfferToday config and implement the shared runtime**

```python
# backend/app/config.py
offertoday_headed_browser_channel: str = "msedge"
offertoday_headed_browser_user_data_dir: Optional[str] = str(
    DEFAULT_RUNTIME_DIR / "manual_actions" / "offertoday-browser-profile"
)
offertoday_headed_browser_executable_path: Optional[str] = None
offertoday_headed_navigation_timeout_ms: int = 60000

@field_validator(
    'anthropic_base_url',
    'anthropic_api_key',
    'custom_api_key',
    'custom_base_url',
    'retrieval_api_url',
    'recommendation_api_url',
    'jobsdb_headed_browser_user_data_dir',
    'jobsdb_headed_browser_executable_path',
    'offertoday_headed_browser_user_data_dir',
    'offertoday_headed_browser_executable_path',
    'ctgoodjobs_proxy_static_url',
    'ctgoodjobs_proxy_pool_api_base_url',
    'ctgoodjobs_proxy_pool_delete_path',
    'ctgoodjobs_proxy_provider_auth_header',
    mode='before',
)
```

```python
# backend/app/scraper/offertoday_browser_runtime.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    ResumeStrategy,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_BASE_URL,
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_SEARCH_URL,
)

_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"


@dataclass(frozen=True)
class OfferTodaySessionCheckResult:
    ok: bool
    listing_count: int
    blocked_reason: str | None = None


class OfferTodayBrowserRuntime:
    def __init__(
        self,
        *,
        headed: bool,
        resume_strategy: ResumeStrategy = RESUME_STRATEGY_FRESH_PROFILE,
        auth_state_path: str | None = None,
        browser_channel: str | None = None,
        browser_profile_path: str | None = None,
        executable_path: str | None = None,
        navigation_timeout_ms: int | None = None,
    ) -> None:
        self.headed = headed
        self.resume_strategy = resume_strategy
        self.auth_state_path = auth_state_path
        self.browser_channel = browser_channel or settings.offertoday_headed_browser_channel
        self.browser_profile_path = browser_profile_path or settings.offertoday_headed_browser_user_data_dir
        self.executable_path = executable_path or settings.offertoday_headed_browser_executable_path
        self.navigation_timeout_ms = (
            navigation_timeout_ms
            if navigation_timeout_ms is not None
            else settings.offertoday_headed_navigation_timeout_ms
        )
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
        return None

    @staticmethod
    def is_waf_challenge_url(url: str | None) -> bool:
        return _WAF_CHALLENGE_PATH in str(url or "")

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        if self.resume_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
            await self._attach_to_live_browser()
        elif self.headed:
            launch_kwargs = {"headless": False}
            if self.executable_path:
                launch_kwargs["executable_path"] = self.executable_path
            else:
                launch_kwargs["channel"] = self.browser_channel
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(Path(self.browser_profile_path).resolve()),
                **launch_kwargs,
            )
        else:
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]
            self._browser = await self._playwright.chromium.launch(headless=True, args=launch_args)
            context_kwargs: dict[str, Any] = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                ),
                "locale": "zh-HK",
            }
            if self.auth_state_path and Path(self.auth_state_path).exists():
                context_kwargs["storage_state"] = str(Path(self.auth_state_path).resolve())
            self._context = await self._browser.new_context(**context_kwargs)

        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await self.warmup()

    async def _attach_to_live_browser(self) -> None:
        session = get_live_browser_registry().get(str(Path(self.browser_profile_path).resolve()))
        if session is None or int(session.debug_port or 0) <= 0:
            raise ManualActionRequiredError(
                source_site="offertoday",
                stage="reuse_open_browser_unavailable",
                blocked_url=f"{OFFERTODAY_BASE_URL}/hk/search",
                message="No reusable OfferToday browser session is available. Open the OfferToday automation browser again or resume with a fresh profile.",
                instructions=[
                    "Reopen the visible OfferToday automation browser for this profile.",
                    "Keep the browser window open after login or WAF verification.",
                    "Retry with Reuse Open Browser, or fall back to Fresh Profile.",
                ],
            )
        self._browser = await self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{session.debug_port}"
        )
        self._context = self._browser.contexts[0] if self._browser.contexts else None
        if self._context is None:
            raise ManualActionRequiredError(
                source_site="offertoday",
                stage="reuse_open_browser_unavailable",
                blocked_url=f"{OFFERTODAY_BASE_URL}/hk/search",
                message="The reusable OfferToday browser session is reachable but exposes no context. Reopen the automation browser and retry.",
                instructions=[
                    "Close the stale OfferToday automation browser window.",
                    "Launch the OfferToday automation browser again and complete login if needed.",
                    "Retry with Reuse Open Browser.",
                ],
            )

    async def warmup(self) -> None:
        await self._page.goto(
            f"{OFFERTODAY_BASE_URL}/hk/search",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await asyncio.sleep(2.0)

    async def fetch_listing_json(self, payload: dict[str, Any], *, listing_url: str | None = None) -> dict[str, Any]:
        url = listing_url or OFFERTODAY_LISTING_SEARCH_URL
        js = f\"\"\"() => fetch('{url}', {{
            method: 'POST',
            headers: {json.dumps(OFFERTODAY_COMMON_HEADERS, ensure_ascii=False)},
            body: JSON.stringify({json.dumps(payload, ensure_ascii=False)})
        }}).then(r => r.json())\"\"\"
        return await self._page.evaluate(js)

    async def fetch_detail_json(self, job_id: str) -> dict[str, Any]:
        detail_url = f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id={job_id}&encryptJobId={job_id}"
        js = f\"\"\"() => fetch('{detail_url}', {{
            headers: {{'api-language': 'zh_HK', 'x-requested-with': 'XMLHttpRequest'}}
        }}).then(r => r.json())\"\"\"
        return await self._page.evaluate(js)

    async def check_session(self, *, category_ids: list[int], keyword: str = "") -> OfferTodaySessionCheckResult:
        payload = {
            "keyword": keyword,
            "salaryType": 0,
            "employmentTypes": [],
            "publishTime": "",
            "experiences": [],
            "educationLevels": [],
            "benefits": [],
            "rcdType": 7,
            "pageSize": 10,
            "page": 1,
            "industries": [],
            "jobFunctionCodes": category_ids,
            "subDistrictCodes": [],
            "needShowDistance": False,
            "searchSource": None,
        }
        response = await self.fetch_listing_json(payload)
        if self.is_waf_challenge_url(getattr(self._page, "url", None)):
            return OfferTodaySessionCheckResult(ok=False, listing_count=0, blocked_reason="waf_challenge")
        result_list = list((response.get("data") or {}).get("resultList") or [])
        return OfferTodaySessionCheckResult(
            ok=response.get("code") == 0,
            listing_count=len(result_list),
            blocked_reason=None if response.get("code") == 0 else str(response.get("code")),
        )

    async def stop(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
```

- [ ] **Step 4: Run the runtime tests to verify they pass**

Run: `python -m pytest -q backend/tests/test_offertoday_browser_runtime.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/scraper/offertoday_browser_runtime.py backend/tests/test_offertoday_browser_runtime.py
git commit -m "feat(offertoday): add reusable browser runtime"
```

### Task 2: Route the detail scraper through the shared runtime

**Files:**
- Modify: `backend/app/scraper/offertoday_browser_detail_scraper.py`
- Modify: `backend/tests/test_offertoday_canonical_and_identity.py`

- [ ] **Step 1: Write the failing detail-scraper tests**

```python
@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_builds_runtime_from_resume_strategy(monkeypatch):
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper")

    observed = {}

    class _FakeRuntime:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def fetch_detail_json(self, job_id: str):
            return {"code": 0, "data": _sample_detail_raw()}

    monkeypatch.setattr(scraper_module, "OfferTodayBrowserRuntime", _FakeRuntime)

    scraper = scraper_cls(
        request_payload={"resume_strategy": "reuse_open_browser"},
        headed=True,
    )

    async with scraper:
        detail_payload = await scraper.fetch_job_detail("jid-1")

    assert observed["resume_strategy"] == "reuse_open_browser"
    assert detail_payload["jobId"] == "jid-1"


@pytest.mark.asyncio
async def test_offertoday_browser_detail_scraper_propagates_manual_action_errors(monkeypatch):
    scraper_module = importlib.import_module("app.scraper.offertoday_browser_detail_scraper")
    scraper_cls = getattr(scraper_module, "OfferTodayBrowserDetailScraper")
    manual_error_cls = importlib.import_module("app.scraper.manual_action").ManualActionRequiredError

    class _FakeRuntime:
        async def __aenter__(self):
            raise manual_error_cls(
                source_site="offertoday",
                stage="reuse_open_browser_unavailable",
                blocked_url="https://www.offertoday.com/hk/search",
                message="missing live session",
            )

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(scraper_module, "OfferTodayBrowserRuntime", lambda **kwargs: _FakeRuntime())

    scraper = scraper_cls(
        request_payload={"resume_strategy": "reuse_open_browser"},
        headed=True,
    )

    with pytest.raises(manual_error_cls):
        async with scraper:
            pass
```

- [ ] **Step 2: Run the detail-scraper tests to verify they fail**

Run: `python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py -k "resume_strategy or manual_action"`
Expected: FAIL because `OfferTodayBrowserDetailScraper` does not accept `request_payload` and still creates its own Playwright runtime directly.

- [ ] **Step 3: Refactor the detail scraper to use `OfferTodayBrowserRuntime`**

```python
from app.scraper.manual_action import RESUME_STRATEGY_FRESH_PROFILE
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime


class OfferTodayBrowserDetailScraper:
    def __init__(
        self,
        *,
        request_payload: dict[str, Any] | None = None,
        detail_json_fetcher: DetailJsonFetcher | None = None,
        auth_state_path: str | None = None,
        headed: bool = False,
        manual_verification_timeout_seconds: int = 180,
    ) -> None:
        self.request_payload = dict(request_payload or {})
        self.resume_strategy = self.request_payload.get("resume_strategy") or RESUME_STRATEGY_FRESH_PROFILE
        self.detail_json_fetcher = detail_json_fetcher
        self.auth_state_path = auth_state_path
        self.headed = headed
        self.manual_verification_timeout_seconds = manual_verification_timeout_seconds
        self._runtime = None
        self._page = None

    async def __aenter__(self):
        if self.detail_json_fetcher is None:
            self._runtime = OfferTodayBrowserRuntime(
                headed=self.headed,
                resume_strategy=self.resume_strategy,
                auth_state_path=self.auth_state_path,
            )
            await self._runtime.__aenter__()
            self._page = self._runtime._page
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._runtime is not None:
            await self._runtime.__aexit__(exc_type, exc, tb)
        self._runtime = None
        self._page = None
        return None

    async def _fetch_detail_payload(self, job_id: str) -> dict[str, Any] | None:
        if self.detail_json_fetcher is not None:
            return await self.detail_json_fetcher(job_id)
        if self._runtime is None:
            raise RuntimeError("OfferTodayBrowserDetailScraper runtime has not been started")
        return await self._runtime.fetch_detail_json(job_id)
```

- [ ] **Step 4: Run the detail-scraper tests to verify they pass**

Run: `python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py -k "resume_strategy or manual_action or ip_block"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scraper/offertoday_browser_detail_scraper.py backend/tests/test_offertoday_canonical_and_identity.py
git commit -m "feat(offertoday): reuse browser runtime for detail scraping"
```

### Task 3: Refactor the standalone crawl path around the shared runtime

**Files:**
- Modify: `backend/scripts/offertoday_standalone_crawl.py`
- Modify: `backend/app/api/crawl_jobs.py`
- Modify: `backend/tests/test_crawl_job_regressions.py`

- [ ] **Step 1: Write the failing crawl-job regressions**

```python
def test_resume_crawl_job_persists_selected_resume_strategy(monkeypatch):
    crawl_job = SimpleNamespace(
        id=uuid4(),
        source_site="offertoday",
        status="manual_action_required",
        request_payload={"crawl_mode": "headed", "crawl_phase": "listing"},
        trigger_type="manual",
        schedule_id=None,
        requested_by="api",
        queued_at=None,
        completed_at=None,
        error_message="previous error",
    )
    latest_event = SimpleNamespace(
        payload={
            "manual_action": {
                "resume_supported": True,
                "resume_context": {"crawl_phase": "listing"},
            }
        }
    )

    service = CrawlJobDispatchService(
        crawl_job_repository=_FakeCrawlJobRepository(crawl_job=crawl_job, latest_event=latest_event),
        event_outbox_repository=_FakeEventOutboxRepository(),
        outbox_publisher=_FakeOutboxPublisher(),
    )

    result = service.resume_crawl_job(
        _FakeDbSession(),
        crawl_job_id=crawl_job.id,
        requested_by="api",
        strategy="reuse_open_browser",
    )

    assert result.request_payload["resume_strategy"] == "reuse_open_browser"


@pytest.mark.asyncio
async def test_create_crawl_job_passes_headed_resume_strategy_to_offertoday_subprocess(monkeypatch):
    subprocess_calls: list[list[str]] = []
    crawl_job_id = uuid4()

    class _FakeDispatchService:
        def dispatch_manual_crawl_job(self, db, **kwargs):
            return SimpleNamespace(
                crawl_job=SimpleNamespace(
                    id=crawl_job_id,
                    request_payload={"max_pages": 50, "crawl_mode": "headed"},
                )
            )

    def fake_popen(args, stdout=None, stderr=None):
        subprocess_calls.append(list(args))
        return SimpleNamespace()

    monkeypatch.setattr(crawl_jobs_api, "dispatch_service", _FakeDispatchService())
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    request = CrawlJobCreateRequest(
        source_site="offertoday",
        crawl_phase="listing",
        category_ids=[],
        max_pages=None,
        crawl_mode="headed",
    )

    await crawl_jobs_api.create_crawl_job(
        request=request,
        response=Response(),
        db=object(),
    )

    assert "--resume-strategy" in subprocess_calls[0]
    assert subprocess_calls[0][subprocess_calls[0].index("--resume-strategy") + 1] == "fresh_profile"
```

- [ ] **Step 2: Run the regressions to verify they fail**

Run: `python -m pytest -q backend/tests/test_crawl_job_regressions.py -k "resume_strategy or subprocess"`
Expected: FAIL because the subprocess command never passes `--resume-strategy` and the standalone script does not expose the new CLI path.

- [ ] **Step 3: Replace ad hoc browser wiring in the standalone crawl path**

```python
# backend/scripts/offertoday_standalone_crawl.py
from app.config import settings
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime


def _build_manual_action_error(*, stage: str, blocked_url: str, message: str) -> ManualActionRequiredError:
    return ManualActionRequiredError(
        source_site="offertoday",
        stage=stage,
        blocked_url=blocked_url,
        message=message,
        instructions=[
            "Open the OfferToday automation browser for the configured profile.",
            "Complete login or the WAF verification challenge and keep the browser open.",
            "Resume with Reuse Open Browser, or rerun with a fresh profile.",
        ],
        resume_context={"crawl_phase": "listing"},
    )


def _record_manual_action_required(db, *, crawl_job_id: str, error: ManualActionRequiredError, crawl_mode: str) -> None:
    CrawlJobRepository().record_runtime_event(
        db,
        crawl_job_id=crawl_job_id,
        status="manual_action_required",
        event_type="crawl.manual_action_required",
        payload={
            "manual_action": error.to_payload(
                crawl_mode=crawl_mode,
                browser_channel=settings.offertoday_headed_browser_channel,
                browser_profile_path=settings.offertoday_headed_browser_user_data_dir,
            )
        },
        emitted_by="offertoday-crawl",
        error_message=error.message,
    )


parser.add_argument("--resume-strategy", default=RESUME_STRATEGY_FRESH_PROFILE)
parser.add_argument("--check", action="store_true", default=False)
parser.add_argument("--smoke-test", action="store_true", default=False)

runtime = OfferTodayBrowserRuntime(
    headed=args.headed,
    resume_strategy=args.resume_strategy,
    auth_state_path=args.auth_state or None,
)

async with runtime:
    if args.check:
        result = await runtime.check_session(category_ids=category_ids or [112000], keyword=(keywords[0] if keywords else ""))
        logger.info("OfferToday session check ok=%s listing_count=%d blocked_reason=%s", result.ok, result.listing_count, result.blocked_reason)
        return

    if args.smoke_test:
        check_result = await runtime.check_session(category_ids=category_ids or [112000], keyword=(keywords[0] if keywords else ""))
        sample_ids = []
        if check_result.ok:
            listing_payload = build_offertoday_listing_payload(category_id=(category_ids[0] if category_ids else 112000), keyword=(keywords[0] if keywords else ""), page=1)
            listing_json = await runtime.fetch_listing_json(listing_payload)
            sample_ids = [str(row.get("jobId") or "").strip() for row in (listing_json.get("data") or {}).get("resultList")[:3]]
        for sample_job_id in [job_id for job_id in sample_ids if job_id]:
            detail_json = await runtime.fetch_detail_json(sample_job_id)
            logger.info("OfferToday smoke detail job_id=%s code=%s", sample_job_id, detail_json.get("code"))
        return
```

```python
# backend/app/api/crawl_jobs.py
_resume_strategy = str(_resolved_request_payload.get("resume_strategy") or "fresh_profile").strip()
_args = [
    "python",
    _script,
    "--category-ids",
    _cat_ids,
    "--auth-state",
    OFFERTODAY_AUTH_STATE_PATH,
    "--resume-strategy",
    _resume_strategy,
]
```

- [ ] **Step 4: Run the regressions to verify they pass**

Run: `python -m pytest -q backend/tests/test_crawl_job_regressions.py -k "resume_strategy or subprocess"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/offertoday_standalone_crawl.py backend/app/api/crawl_jobs.py backend/tests/test_crawl_job_regressions.py
git commit -m "feat(offertoday): add reusable-browser crawl flow"
```

### Task 4: Upgrade auth setup and transport bakeoff into setup/check/smoke tools

**Files:**
- Modify: `backend/scripts/offertoday_auth_setup.py`
- Modify: `backend/scripts/offertoday_transport_bakeoff.py`
- Test: `backend/tests/test_offertoday_browser_runtime.py`

- [ ] **Step 1: Extend the runtime tests with smoke helper coverage**

```python
@pytest.mark.asyncio
async def test_runtime_smoke_probe_reports_detail_codes(monkeypatch):
    from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime

    class _FakeRuntime(OfferTodayBrowserRuntime):
        async def check_session(self, *, category_ids: list[int], keyword: str = ""):
            return SimpleNamespace(ok=True, listing_count=2, blocked_reason=None)

        async def fetch_listing_json(self, payload, *, listing_url=None):
            return {"code": 0, "data": {"resultList": [{"jobId": "job-1"}, {"jobId": "job-2"}]}}

        async def fetch_detail_json(self, job_id: str):
            return {"code": -1000035 if job_id == "job-2" else 0, "data": {"jobId": job_id}}

    runtime = _FakeRuntime(headed=False)
    runtime._page = _FakePage()

    result = await runtime.run_smoke_test(category_ids=[112000], keyword="data", detail_limit=2)

    assert result["listing_ok"] is True
    assert result["detail_results"][0]["code"] == 0
    assert result["detail_results"][1]["code"] == -1000035
```

- [ ] **Step 2: Run the smoke-helper test to verify it fails**

Run: `python -m pytest -q backend/tests/test_offertoday_browser_runtime.py -k smoke`
Expected: FAIL because `run_smoke_test` does not exist yet.

- [ ] **Step 3: Add profile-first setup and runtime-backed bakeoff flows**

```python
# backend/scripts/offertoday_auth_setup.py
from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry

parser.add_argument("--browser-profile", default=settings.offertoday_headed_browser_user_data_dir)
parser.add_argument("--cdp-port", type=int, default=9222)
parser.add_argument("--register-live-session", action="store_true", default=False)

context = await pw.chromium.launch_persistent_context(
    user_data_dir=str(Path(args.browser_profile).resolve()),
    headless=False,
    channel=settings.offertoday_headed_browser_channel,
    args=[
        "--start-maximized",
        f"--remote-debugging-port={args.cdp_port}",
    ],
)

if args.register_live_session:
    get_live_browser_registry().register(
        browser_channel=settings.offertoday_headed_browser_channel,
        browser_profile_path=str(Path(args.browser_profile).resolve()),
        blocked_url=_OFFERTODAY_SEARCH,
        debug_port=args.cdp_port,
        status="live",
    )
```

```python
# backend/app/scraper/offertoday_browser_runtime.py
    async def run_smoke_test(
        self,
        *,
        category_ids: list[int],
        keyword: str = "",
        detail_limit: int = 3,
    ) -> dict[str, Any]:
        check_result = await self.check_session(category_ids=category_ids, keyword=keyword)
        listing_payload = {
            "keyword": keyword,
            "salaryType": 0,
            "employmentTypes": [],
            "publishTime": "",
            "experiences": [],
            "educationLevels": [],
            "benefits": [],
            "rcdType": 7,
            "pageSize": 10,
            "page": 1,
            "industries": [],
            "jobFunctionCodes": category_ids,
            "subDistrictCodes": [],
            "needShowDistance": False,
            "searchSource": None,
        }
        listing_json = await self.fetch_listing_json(listing_payload)
        sample_ids = [
            str(row.get("jobId") or "").strip()
            for row in (listing_json.get("data") or {}).get("resultList", [])[: max(int(detail_limit or 0), 0)]
            if str(row.get("jobId") or "").strip()
        ]
        detail_results = []
        for sample_job_id in sample_ids:
            detail_json = await self.fetch_detail_json(sample_job_id)
            detail_results.append({"job_id": sample_job_id, "code": detail_json.get("code")})
        return {
            "listing_ok": check_result.ok,
            "listing_count": check_result.listing_count,
            "blocked_reason": check_result.blocked_reason,
            "detail_results": detail_results,
        }
```

```python
# backend/scripts/offertoday_transport_bakeoff.py
from app.scraper.manual_action import (
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime

async def _run_candidate(name: str, *, resume_strategy: str, auth_state_path: str | None, category: int, keyword: str, detail_limit: int) -> TransportResult:
    async with OfferTodayBrowserRuntime(
        headed=True,
        resume_strategy=resume_strategy,
        auth_state_path=auth_state_path,
    ) as runtime:
        smoke = await runtime.run_smoke_test(
            category_ids=[category],
            keyword=keyword,
            detail_limit=detail_limit,
        )
    return TransportResult(
        name=name,
        listing_success=smoke["listing_ok"],
        listing_count=smoke["listing_count"],
        detail_success_count=sum(1 for row in smoke["detail_results"] if row["code"] == 0),
        detail_attempted=len(smoke["detail_results"]),
        detail_errors=[f'{row["job_id"]}: code={row["code"]}' for row in smoke["detail_results"] if row["code"] != 0],
    )

results.append(await _run_candidate("fresh-profile", resume_strategy=RESUME_STRATEGY_FRESH_PROFILE, auth_state_path=None, category=args.category, keyword=args.keywords, detail_limit=args.details))
if args.auth_state:
    results.append(await _run_candidate("storage-state", resume_strategy=RESUME_STRATEGY_FRESH_PROFILE, auth_state_path=args.auth_state, category=args.category, keyword=args.keywords, detail_limit=args.details))
results.append(await _run_candidate("reuse-open-browser", resume_strategy=RESUME_STRATEGY_REUSE_OPEN_BROWSER, auth_state_path=None, category=args.category, keyword=args.keywords, detail_limit=args.details))
```

- [ ] **Step 4: Run the runtime smoke-helper test to verify it passes**

Run: `python -m pytest -q backend/tests/test_offertoday_browser_runtime.py -k smoke`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/offertoday_auth_setup.py backend/scripts/offertoday_transport_bakeoff.py backend/app/scraper/offertoday_browser_runtime.py backend/tests/test_offertoday_browser_runtime.py
git commit -m "feat(offertoday): add setup and smoke tooling"
```

### Task 5: Verify the full OfferToday path against the approved spec

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-offertoday-manual-action-integration.md` only if self-review finds a mismatch

- [ ] **Step 1: Run focused backend tests**

Run: `python -m pytest -q backend/tests/test_offertoday_browser_runtime.py backend/tests/test_offertoday_canonical_and_identity.py backend/tests/test_crawl_job_regressions.py`
Expected: PASS

- [ ] **Step 2: Run OfferToday setup against the dedicated browser profile**

Run:

```bash
python backend/scripts/offertoday_auth_setup.py --browser-profile backend/runtime/manual_actions/offertoday-browser-profile --register-live-session --cdp-port 9222 --timeout 300
```

Expected:
- a visible browser opens with the OfferToday automation profile
- after login or WAF verification, the script reports a saved session
- the live session is registered for later CDP attach

- [ ] **Step 3: Run the OfferToday session check**

Run:

```bash
python backend/scripts/offertoday_standalone_crawl.py --category-ids 112000 --headed --resume-strategy reuse_open_browser --check
```

Expected:
- exit 0
- log line confirms `ok=True` or an explicit `blocked_reason`
- no ambiguous parser-style failure when the session itself is unhealthy

- [ ] **Step 4: Run the OfferToday smoke test**

Run:

```bash
python backend/scripts/offertoday_standalone_crawl.py --category-ids 112000 --headed --resume-strategy reuse_open_browser --smoke-test
```

Expected:
- listing probe executes
- 1-3 detail probes execute
- any `-1000035` response is reported explicitly as a session/WAF outcome

- [ ] **Step 5: Compare implementation against the spec**

Check:
- OfferToday has its own browser settings
- OfferToday runtime supports `fresh_profile` and `reuse_open_browser`
- detail scraper and standalone crawl share the same runtime
- setup/check/smoke flows exist
- `storage_state` remains supported as fallback rather than the main path

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/scraper/offertoday_browser_runtime.py backend/app/scraper/offertoday_browser_detail_scraper.py backend/scripts/offertoday_standalone_crawl.py backend/scripts/offertoday_auth_setup.py backend/scripts/offertoday_transport_bakeoff.py backend/app/api/crawl_jobs.py backend/tests/test_offertoday_browser_runtime.py backend/tests/test_offertoday_canonical_and_identity.py backend/tests/test_crawl_job_regressions.py
git commit -m "feat(offertoday): integrate reusable browser manual-action flow"
```
