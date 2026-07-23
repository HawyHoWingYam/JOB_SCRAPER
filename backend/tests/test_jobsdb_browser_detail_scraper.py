from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.scraper import jobsdb_browser_detail_scraper as jobsdb_browser_module
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.scraper.jobsdb_profile_recovery import (
    LIVENESS_DEAD,
    LIVENESS_UNKNOWN,
    PROFILE_SCOPE_FIXED,
    PROFILE_SCOPE_FRESH,
    reset_profile,
)
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

    def close(self) -> None:
        return None


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
            "crawl_mode": "headless",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("crawl_mode", "expected_headless"),
    [("headless", True), ("headed", False)],
)
async def test_jobsdb_fresh_browser_uses_reviewed_crawl_mode(
    monkeypatch: pytest.MonkeyPatch,
    crawl_mode: str,
    expected_headless: bool,
) -> None:
    context = _FakeContext()
    chromium = _FakeChromium(_FakeBrowser(context))
    fake_playwright = _FakePlaywright(chromium)
    launch_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(fake_playwright),
    )

    def fake_launch(_chromium, **kwargs):
        launch_calls.append(kwargs)
        return SimpleNamespace(
            context=context,
            attempted_fallback=False,
            requested_channel=kwargs.get("browser_channel"),
            resolved_channel=kwargs.get("browser_channel"),
        )

    monkeypatch.setattr(
        jobsdb_browser_module,
        "launch_persistent_context_with_fallback",
        fake_launch,
    )

    scraper = JobsDBBrowserDetailScraper(
        request_payload={
            "crawl_job_id": f"crawl-jobsdb-{crawl_mode}",
            "crawl_mode": crawl_mode,
            "resume_strategy": "fresh_profile",
        },
        user_data_dir=f"/tmp/jobsdb-{crawl_mode}",
    )

    async with scraper:
        pass

    assert scraper.crawl_mode == crawl_mode
    assert len(launch_calls) == 1
    assert launch_calls[0]["headless"] is expected_headless


@pytest.mark.asyncio
async def test_jobsdb_resume_fresh_profile_retries_once_after_safe_stale_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _FakeContext()
    fake_playwright = _FakePlaywright(_FakeChromium(_FakeBrowser(context)))
    launch_calls: list[dict[str, object]] = []
    cleanup_calls: list[Path] = []

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(fake_playwright),
    )

    def fake_launch(_chromium, **kwargs):
        launch_calls.append(kwargs)
        if len(launch_calls) == 1:
            raise RuntimeError(
                "launch_persistent_context: Target page, context or browser has been closed"
            )
        return SimpleNamespace(
            context=context,
            attempted_fallback=False,
            requested_channel=kwargs.get("browser_channel"),
            resolved_channel=kwargs.get("browser_channel"),
        )

    monkeypatch.setattr(
        jobsdb_browser_module,
        "launch_persistent_context_with_fallback",
        fake_launch,
    )
    monkeypatch.setattr(
        jobsdb_browser_module,
        "cleanup_profile",
        lambda path, **_kwargs: (
            cleanup_calls.append(path)
            or SimpleNamespace(
                available=True,
                liveness=SimpleNamespace(state="dead"),
                reason=None,
            )
        ),
    )

    scraper = JobsDBBrowserDetailScraper(
        request_payload={
            "crawl_job_id": str(uuid4()),
            "crawl_mode": "headless",
            "resume_strategy": "fresh_profile",
            "is_resume": True,
        },
        user_data_dir="/tmp/jobsdb-retry-root",
    )

    async with scraper:
        pass

    assert len(launch_calls) == 2
    assert launch_calls[0]["headless"] is True
    assert launch_calls[1]["headless"] is True
    assert len(cleanup_calls) == 2


def test_jobsdb_headless_profile_error_uses_worker_recovery_guidance() -> None:
    scraper = JobsDBBrowserDetailScraper(
        request_payload={"crawl_mode": "headless"},
    )

    with pytest.raises(ManualActionRequiredError) as raised:
        scraper._raise_if_profile_in_use(
            RuntimeError(
                "launch_persistent_context: Target page, context or browser has been closed"
            )
        )

    assert raised.value.stage == "browser_profile_in_use"
    assert raised.value.action_type == "profile_recovery"
    assert "Edge" not in raised.value.message
    assert "Reset Browser Profile" in raised.value.instructions[0]


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


class _ProfileRegistry:
    def __init__(self, session=None) -> None:
        self.session = session
        self.removed: list[str] = []

    def get(self, _profile):
        return self.session

    def remove(self, profile):
        self.removed.append(profile)


def test_reset_profile_recreates_task_owned_profile_without_preserving_browser_state(
    tmp_path: Path,
) -> None:
    crawl_job_id = uuid4()
    profile = tmp_path / "tasks" / str(crawl_job_id)
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("login state", encoding="utf-8")
    (profile / "SingletonLock").write_text("stale", encoding="utf-8")
    registry = _ProfileRegistry()

    result = reset_profile(
        profile,
        profile_scope=PROFILE_SCOPE_FRESH,
        browser_channel="chromium",
        process_lister=lambda: [],
        registry=registry,
    )

    assert result.available is True
    assert result.liveness.state == LIVENESS_DEAD
    assert result.recreated is True
    assert profile.is_dir()
    assert not (profile / "Cookies").exists()
    assert not (profile / "SingletonLock").exists()
    assert registry.removed == [str(profile)]


def test_reset_profile_fixed_profile_only_removes_lock_markers(tmp_path: Path) -> None:
    profile = tmp_path / "fixed"
    profile.mkdir()
    (profile / "Cookies").write_text("login state", encoding="utf-8")
    (profile / "SingletonLock").write_text("stale", encoding="utf-8")
    (profile / "SingletonSocket").write_text("stale", encoding="utf-8")
    registry = _ProfileRegistry()

    result = reset_profile(
        profile,
        profile_scope=PROFILE_SCOPE_FIXED,
        browser_channel="msedge",
        process_lister=lambda: [],
        registry=registry,
    )

    assert result.available is True
    assert result.recreated is False
    assert result.removed_lock_markers == ("SingletonLock", "SingletonSocket")
    assert (profile / "Cookies").read_text(encoding="utf-8") == "login state"
    assert registry.removed == [str(profile)]


def test_reset_profile_fails_closed_when_process_liveness_is_unknown(tmp_path: Path) -> None:
    profile = tmp_path / "fixed"
    profile.mkdir()
    (profile / "SingletonLock").write_text("possibly live", encoding="utf-8")
    registry = _ProfileRegistry()

    result = reset_profile(
        profile,
        profile_scope=PROFILE_SCOPE_FIXED,
        process_lister=lambda: (_ for _ in ()).throw(
            RuntimeError("process inspection unavailable")
        ),
        registry=registry,
    )

    assert result.available is False
    assert result.liveness.state == LIVENESS_UNKNOWN
    assert result.reason == "profile_liveness_unknown"
    assert (profile / "SingletonLock").exists()
    assert registry.removed == []


def test_reset_profile_refuses_a_matching_live_process(tmp_path: Path) -> None:
    profile = tmp_path / "fixed"
    profile.mkdir()
    registry = _ProfileRegistry()

    result = reset_profile(
        profile,
        profile_scope=PROFILE_SCOPE_FIXED,
        browser_channel="chromium",
        process_lister=lambda: [
            {
                "pid": 123,
                "name": "chromium",
                "cmdline": ["chromium", f"--user-data-dir={profile}"],
            }
        ],
        registry=registry,
    )

    assert result.available is False
    assert result.liveness.state == "live"
    assert result.reason == "profile_is_in_use"
    assert registry.removed == []
