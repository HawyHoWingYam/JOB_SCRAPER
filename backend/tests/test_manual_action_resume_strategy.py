from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import logging
import sys
from types import ModuleType
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import crawl_jobs
from app.database import get_db
from app.host_manual_action_helper import capture_manual_action_screenshot
from app.manual_actions.live_browser_registry import LiveBrowserRegistry
from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
from app.scraper.jobsdb_browser_detail_scraper import JobsDBBrowserDetailScraper
from app.scraper.manual_action import ManualActionRequiredError
from app.scraper.proxy_rotation import ProxyLease
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


class FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshed: list[object] = []

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:
        self.refreshed.append(obj)


class FakeCrawlJobRepository:
    def __init__(
        self,
        *,
        crawl_job,
        latest_event,
        historical_events: list[object] | None = None,
    ) -> None:
        self.crawl_job = crawl_job
        self.latest_event = latest_event
        self.historical_events = list(historical_events or [])
        self.appended_events: list[dict[str, object]] = []

    def get_crawl_job_by_id(self, db, crawl_job_id):
        return self.crawl_job

    def get_latest_manual_action_event(self, db, crawl_job_id):
        return self.latest_event

    def append_event(
        self,
        db,
        *,
        crawl_job_id,
        event_type,
        payload,
        emitted_by,
        auto_commit,
    ) -> None:
        self.appended_events.append(
            {
                "crawl_job_id": crawl_job_id,
                "event_type": event_type,
                "payload": payload,
                "emitted_by": emitted_by,
                "auto_commit": auto_commit,
            }
        )

    def list_events(self, db, crawl_job_id):
        return list(self.historical_events)


class FakeEventOutboxRepository:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    def enqueue(self, db, **kwargs) -> None:
        row = SimpleNamespace(
            id=len(self.enqueued) + 1,
            status="pending",
            attempt_count=0,
            published_at=None,
            last_error=None,
            **kwargs,
        )
        self.enqueued.append(row)
        return row


class FakeOutboxPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.row_calls: list[dict[str, object]] = []

    def publish_row(self, db, *, row) -> bool:
        self.row_calls.append({"db": db, "row": row})
        return True

    def publish_pending_batch(self, db, *, limit: int) -> None:
        self.calls.append({"db": db, "limit": limit})


class FakeDispatchService:
    def __init__(self, crawl_job) -> None:
        self.crawl_job = crawl_job
        self.calls: list[dict[str, object]] = []

    def resume_crawl_job(self, db, *, crawl_job_id, requested_by, strategy=None):
        self.calls.append(
            {
                "db": db,
                "crawl_job_id": crawl_job_id,
                "requested_by": requested_by,
                "strategy": strategy,
            }
        )
        return self.crawl_job


class FakePage:
    def __init__(
        self,
        *,
        html: str = "<html></html>",
        title_text: str = "",
        url: str = "https://example.test/page",
        screenshot_bytes: bytes = b"fake-png",
    ) -> None:
        self.events: list[tuple[str, object]] = []
        self.html = html
        self.title_text = title_text
        self.url = url
        self.screenshot_bytes = screenshot_bytes

    def goto(self, url: str, *, wait_until: str, timeout: int | None = None):
        self.url = url
        self.events.append(("goto", {"url": url, "wait_until": wait_until, "timeout": timeout}))
        return None

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.events.append(("wait_for_timeout", milliseconds))

    def content(self) -> str:
        self.events.append(("content", None))
        return self.html

    def title(self) -> str:
        self.events.append(("title", None))
        return self.title_text

    def screenshot(self, *, type: str, full_page: bool) -> bytes:
        self.events.append(("screenshot", {"type": type, "full_page": full_page}))
        return self.screenshot_bytes


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        self.pages = list(pages or [])
        self.closed = False
        self.default_navigation_timeout = None
        self.new_page_calls = 0

    def set_default_navigation_timeout(self, milliseconds: int) -> None:
        self.default_navigation_timeout = milliseconds

    def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext] | None = None) -> None:
        self.contexts = list(contexts or [])
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(
        self,
        *,
        persistent_context: FakeContext | None = None,
        browser: FakeBrowser | None = None,
        connect_exception: Exception | None = None,
        launch_exception: Exception | None = None,
    ) -> None:
        self.persistent_context = persistent_context or FakeContext()
        self.browser = browser or FakeBrowser([FakeContext([FakePage()])])
        self.connect_exception = connect_exception
        self.launch_exception = launch_exception
        self.launch_calls: list[dict[str, object]] = []
        self.connect_calls: list[str] = []

    def launch_persistent_context(self, *, user_data_dir: str, **kwargs) -> FakeContext:
        self.launch_calls.append({"user_data_dir": user_data_dir, **kwargs})
        if self.launch_exception is not None:
            raise self.launch_exception
        return self.persistent_context

    def connect_over_cdp(self, endpoint_url: str) -> FakeBrowser:
        self.connect_calls.append(endpoint_url)
        if self.connect_exception is not None:
            raise self.connect_exception
        return self.browser


class FakePlaywrightHandle:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeSyncPlaywrightFactory:
    def __init__(self, handle: FakePlaywrightHandle) -> None:
        self.handle = handle

    def start(self) -> FakePlaywrightHandle:
        return self.handle


def _build_crawl_job(*, status: str = "manual_action_required", request_payload: dict | None = None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        source_site="jobsdb",
        trigger_type="manual",
        schedule_id=None,
        status=status,
        request_payload=dict(request_payload or {"crawl_phase": "listing", "crawl_mode": "headed"}),
        requested_by="tester",
        queued_at=now,
        started_at=None,
        completed_at=None,
        error_message="blocked",
        metrics=None,
        created_at=now,
        updated_at=now,
    )


def _build_resume_client(monkeypatch, dispatch_service):
    app = FastAPI()
    app.include_router(crawl_jobs.router, prefix="/api/v1")
    db = object()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(crawl_jobs, "dispatch_service", dispatch_service)
    return TestClient(app), dispatch_service, db


def _build_service(*, crawl_job, manual_action: dict, historical_events: list[object] | None = None):
    repository = FakeCrawlJobRepository(
        crawl_job=crawl_job,
        latest_event=SimpleNamespace(payload={"manual_action": manual_action}),
        historical_events=historical_events,
    )
    outbox_repository = FakeEventOutboxRepository()
    outbox_publisher = FakeOutboxPublisher()
    service = CrawlJobDispatchService(
        crawl_job_repository=repository,
        event_outbox_repository=outbox_repository,
        outbox_publisher=outbox_publisher,
    )
    return service, repository, outbox_repository, outbox_publisher


class FakeDispatchCrawlJobRepository:
    def __init__(self) -> None:
        self.created_jobs: list[object] = []
        self.appended_events: list[dict[str, object]] = []

    def create_crawl_job(
        self,
        db,
        *,
        source_site,
        trigger_type,
        request_payload,
        requested_by,
        schedule_id,
        status,
        auto_commit,
    ):
        now = datetime.now(timezone.utc)
        crawl_job = SimpleNamespace(
            id=uuid4(),
            source_site=source_site,
            trigger_type=trigger_type,
            schedule_id=schedule_id,
            status=status,
            request_payload=dict(request_payload),
            requested_by=requested_by,
            queued_at=now,
            started_at=None,
            completed_at=None,
            error_message=None,
            metrics=None,
            created_at=now,
            updated_at=now,
        )
        self.created_jobs.append(crawl_job)
        return crawl_job

    def append_event(
        self,
        db,
        *,
        crawl_job_id,
        event_type,
        payload,
        emitted_by,
        auto_commit,
    ) -> None:
        self.appended_events.append(
            {
                "crawl_job_id": crawl_job_id,
                "event_type": event_type,
                "payload": payload,
                "emitted_by": emitted_by,
                "auto_commit": auto_commit,
            }
        )


def _install_fake_playwright(monkeypatch, chromium: FakeChromium) -> FakePlaywrightHandle:
    handle = FakePlaywrightHandle(chromium)
    fake_sync_api = ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywrightFactory(handle)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    return handle


async def _open_and_close(scraper):
    async with scraper:
        return {
            "page": scraper._sync_page,
            "context": scraper._sync_context,
            "browser": getattr(scraper, "_sync_browser", None),
        }


async def _open_only(scraper):
    return await scraper.__aenter__()


def test_resume_endpoint_accepts_omitted_body_and_uses_legacy_semantics(monkeypatch):
    crawl_job = _build_crawl_job(status="dispatching", request_payload={"resume_strategy": "fresh_profile"})
    dispatch_service = FakeDispatchService(crawl_job)
    client, _, db = _build_resume_client(monkeypatch, dispatch_service)

    response = client.post(f"/api/v1/crawl-jobs/{crawl_job.id}/resume")

    assert response.status_code == 200
    assert dispatch_service.calls == [
        {
            "db": db,
            "crawl_job_id": crawl_job.id,
            "requested_by": "api",
            "strategy": None,
        }
    ]
    assert response.json()["request_payload"]["resume_strategy"] == "fresh_profile"


def test_resume_endpoint_rejects_unsupported_strategy_values(monkeypatch):
    crawl_job = _build_crawl_job()
    dispatch_service = FakeDispatchService(crawl_job)
    client, _, _ = _build_resume_client(monkeypatch, dispatch_service)

    response = client.post(
        f"/api/v1/crawl-jobs/{crawl_job.id}/resume",
        json={"strategy": "definitely-not-supported"},
    )

    assert response.status_code == 422
    assert dispatch_service.calls == []


def test_resume_service_stores_reuse_open_browser_strategy_and_logs_it():
    crawl_job = _build_crawl_job()
    service, repository, outbox_repository, outbox_publisher = _build_service(
        crawl_job=crawl_job,
        manual_action={
            "resume_supported": True,
            "resume_context": {"crawl_phase": "listing", "cursor": "next-page"},
        },
    )
    db = FakeDB()

    resumed_job = service.resume_crawl_job(
        db,
        crawl_job_id=crawl_job.id,
        requested_by="api",
        strategy="reuse_open_browser",
    )

    assert resumed_job is crawl_job
    assert crawl_job.status == "dispatching"
    assert crawl_job.request_payload["is_resume"] is True
    assert crawl_job.request_payload["resume_context"] == {
        "crawl_phase": "listing",
        "cursor": "next-page",
    }
    assert crawl_job.request_payload["resume_strategy"] == "reuse_open_browser"
    assert repository.appended_events[0]["event_type"] == "crawl.resume_requested"
    assert repository.appended_events[0]["payload"]["strategy"] == "reuse_open_browser"
    assert repository.appended_events[1]["payload"]["request_payload"]["resume_strategy"] == "reuse_open_browser"
    assert outbox_repository.enqueued[0].event_type == "crawl.requested"
    assert outbox_publisher.row_calls == [{"db": db, "row": outbox_repository.enqueued[0]}]
    assert outbox_publisher.calls == [{"db": db, "limit": 100}]
    assert db.commits == 1
    assert db.refreshed == [crawl_job]


def test_resume_service_uses_fresh_profile_when_strategy_is_omitted():
    crawl_job = _build_crawl_job()
    service, repository, _, _ = _build_service(
        crawl_job=crawl_job,
        manual_action={
            "resume_supported": True,
            "resume_context": {"crawl_phase": "listing"},
        },
    )
    db = FakeDB()

    service.resume_crawl_job(
        db,
        crawl_job_id=crawl_job.id,
        requested_by="api",
    )

    assert crawl_job.request_payload["resume_strategy"] == "fresh_profile"
    assert repository.appended_events[0]["payload"]["strategy"] == "fresh_profile"


def test_dispatch_manual_crawl_job_publishes_its_command_row_immediately():
    repository = FakeDispatchCrawlJobRepository()
    outbox_repository = FakeEventOutboxRepository()
    outbox_publisher = FakeOutboxPublisher()
    service = CrawlJobDispatchService(
        crawl_job_repository=repository,
        event_outbox_repository=outbox_repository,
        outbox_publisher=outbox_publisher,
    )
    db = FakeDB()

    result = service.dispatch_manual_crawl_job(
        db,
        source_site="ctgoodjobs",
        crawl_phase="detail",
        crawl_mode="headed",
        category_ids=["ctgoodjobs:021"],
        max_pages=3,
        detail_limit=500,
        skip_existing=True,
        requested_by="api",
    )

    assert result.crawl_job is repository.created_jobs[0]
    assert outbox_repository.enqueued[0].topic == "stream.crawl.commands.headed"
    assert outbox_repository.enqueued[0].event_type == "crawl.requested"
    assert outbox_publisher.row_calls == [{"db": db, "row": outbox_repository.enqueued[0]}]
    assert outbox_publisher.calls == [{"db": db, "limit": 100}]


def test_resume_service_rejects_non_manual_action_jobs():
    crawl_job = _build_crawl_job(status="completed")
    service, _, _, _ = _build_service(
        crawl_job=crawl_job,
        manual_action={"resume_supported": True, "resume_context": {"crawl_phase": "listing"}},
    )

    with pytest.raises(RuntimeError, match="cannot be resumed"):
        service.resume_crawl_job(
            FakeDB(),
            crawl_job_id=crawl_job.id,
            requested_by="api",
        )


def test_resume_service_does_not_coerce_falsey_invalid_strategy_to_legacy_default():
    crawl_job = _build_crawl_job()
    service, _, _, _ = _build_service(
        crawl_job=crawl_job,
        manual_action={"resume_supported": True, "resume_context": {"crawl_phase": "listing"}},
    )

    with pytest.raises(RuntimeError, match="Unsupported resume strategy"):
        service.resume_crawl_job(
            FakeDB(),
            crawl_job_id=crawl_job.id,
            requested_by="api",
            strategy="",
        )


def test_manual_action_payload_includes_reuse_open_browser_metadata():
    error = ManualActionRequiredError(
        source_site="jobsdb",
        stage="listing",
        blocked_url="https://example.test/challenge",
        message="Solve the challenge and resume.",
    )

    payload = error.to_payload(
        crawl_mode="headed",
        browser_channel="msedge",
        browser_profile_path=r"C:\profiles\jobsdb",
    )

    assert payload["resume_supported"] is True
    assert payload["browser_channel"] == "msedge"
    assert payload["browser_profile_path"] == r"C:\profiles\jobsdb"
    assert payload["reuse_open_browser_supported"] is True
    assert payload["preferred_resume_strategy"] == "reuse_open_browser"


@pytest.mark.parametrize(
    "scraper_cls",
    [JobsDBBrowserDetailScraper, CTGoodJobsBrowserPageScraper],
)
def test_reuse_open_browser_attaches_via_cdp_and_detaches_without_closing_visible_browser(
    monkeypatch,
    scraper_cls,
):
    profile_path = r"C:\profiles\reuse-open-browser"
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=profile_path,
        blocked_url="https://example.test/challenge",
        debug_port=45555,
    )
    existing_page = FakePage()
    attached_context = FakeContext([existing_page])
    chromium = FakeChromium(browser=FakeBrowser([attached_context]))
    handle = _install_fake_playwright(monkeypatch, chromium)
    monkeypatch.setattr(f"{scraper_cls.__module__}.get_live_browser_registry", lambda: registry)

    result = asyncio.run(
        _open_and_close(
            scraper_cls(
                request_payload={"resume_strategy": "reuse_open_browser"},
                user_data_dir=profile_path,
                browser_channel="msedge",
            )
        )
    )

    assert chromium.connect_calls == ["http://127.0.0.1:45555"]
    assert chromium.launch_calls == []
    assert result["context"] is attached_context
    assert result["page"] is existing_page
    assert attached_context.new_page_calls == 0
    assert attached_context.closed is False
    assert result["browser"].closed is False
    assert handle.stopped is True


@pytest.mark.parametrize(
    "scraper_cls",
    [JobsDBBrowserDetailScraper, CTGoodJobsBrowserPageScraper],
)
def test_fresh_profile_launches_persistent_context_and_closes_it_on_exit(monkeypatch, scraper_cls):
    persistent_context = FakeContext([FakePage()])
    chromium = FakeChromium(persistent_context=persistent_context)
    handle = _install_fake_playwright(monkeypatch, chromium)

    result = asyncio.run(
        _open_and_close(
            scraper_cls(
                request_payload={"resume_strategy": "fresh_profile"},
                user_data_dir=r"C:\profiles\fresh-profile",
                browser_channel="msedge",
            )
        )
    )

    assert len(chromium.launch_calls) == 1
    assert chromium.connect_calls == []
    assert result["context"] is persistent_context
    assert persistent_context.closed is True
    assert result["browser"] is None
    assert handle.stopped is True


def test_ctgoodjobs_fresh_profile_launches_persistent_context_with_proxy_when_enabled(monkeypatch):
    persistent_context = FakeContext([FakePage()])
    chromium = FakeChromium(persistent_context=persistent_context)
    _install_fake_playwright(monkeypatch, chromium)
    monkeypatch.setattr(
        "app.scraper.ctgoodjobs_browser_page_scraper.settings",
        SimpleNamespace(
            jobsdb_headed_browser_channel="msedge",
            jobsdb_headed_browser_user_data_dir=None,
            jobsdb_headed_browser_executable_path=None,
            jobsdb_headed_navigation_timeout_ms=60000,
            ctgoodjobs_proxy_enabled=True,
            ctgoodjobs_proxy_provider="static",
            ctgoodjobs_proxy_static_url="http://proxy.example:8080",
            ctgoodjobs_proxy_pool_api_base_url=None,
            ctgoodjobs_proxy_pool_get_path="/get",
            ctgoodjobs_proxy_pool_delete_path="/delete",
            ctgoodjobs_proxy_request_timeout_s=30.0,
            ctgoodjobs_proxy_quarantine_minutes_challenge=15,
            ctgoodjobs_proxy_quarantine_minutes_network=10,
            ctgoodjobs_proxy_min_seconds_between_reuse=0.0,
            ctgoodjobs_proxy_require_https_capable=False,
            ctgoodjobs_proxy_provider_auth_header=None,
        ),
    )

    asyncio.run(
        _open_and_close(
            CTGoodJobsBrowserPageScraper(
                request_payload={"resume_strategy": "fresh_profile"},
                user_data_dir=r"C:\profiles\ctgoodjobs-fresh-proxy",
                browser_channel="msedge",
            )
        )
    )

    assert chromium.launch_calls[0]["proxy"] == {"server": "http://proxy.example:8080"}


def test_ctgoodjobs_fresh_profile_launches_persistent_context_with_proxy_credentials(monkeypatch):
    persistent_context = FakeContext([FakePage()])
    chromium = FakeChromium(persistent_context=persistent_context)
    _install_fake_playwright(monkeypatch, chromium)
    monkeypatch.setattr(
        "app.scraper.ctgoodjobs_browser_page_scraper.settings",
        SimpleNamespace(
            jobsdb_headed_browser_channel="msedge",
            jobsdb_headed_browser_user_data_dir=None,
            jobsdb_headed_browser_executable_path=None,
            jobsdb_headed_navigation_timeout_ms=60000,
            ctgoodjobs_proxy_enabled=True,
            ctgoodjobs_proxy_provider="static",
            ctgoodjobs_proxy_static_url="http://user-1:pass-2@proxy.example:8080",
            ctgoodjobs_proxy_pool_api_base_url=None,
            ctgoodjobs_proxy_pool_get_path="/get",
            ctgoodjobs_proxy_pool_delete_path="/delete",
            ctgoodjobs_proxy_request_timeout_s=30.0,
            ctgoodjobs_proxy_quarantine_minutes_challenge=15,
            ctgoodjobs_proxy_quarantine_minutes_network=10,
            ctgoodjobs_proxy_min_seconds_between_reuse=0.0,
            ctgoodjobs_proxy_require_https_capable=False,
            ctgoodjobs_proxy_provider_auth_header=None,
        ),
    )

    asyncio.run(
        _open_and_close(
            CTGoodJobsBrowserPageScraper(
                request_payload={"resume_strategy": "fresh_profile"},
                user_data_dir=r"C:\profiles\ctgoodjobs-fresh-proxy-auth",
                browser_channel="msedge",
            )
        )
    )

    assert chromium.launch_calls[0]["proxy"] == {
        "server": "http://proxy.example:8080",
        "username": "user-1",
        "password": "pass-2",
    }


def test_ctgoodjobs_fresh_profile_converts_missing_proxy_lease_into_manual_action_error(monkeypatch):
    persistent_context = FakeContext([FakePage()])
    chromium = FakeChromium(persistent_context=persistent_context)
    handle = _install_fake_playwright(monkeypatch, chromium)

    class FailingProxyRuntime:
        enabled = True

        async def acquire_lease(self):
            raise RuntimeError("Unable to acquire a usable CTGoodJobs proxy lease")

        def build_playwright_proxy_config(self, _lease):
            return None

    scraper = CTGoodJobsBrowserPageScraper(
        request_payload={"resume_strategy": "fresh_profile"},
        user_data_dir=r"C:\profiles\ctgoodjobs-missing-proxy-lease",
        browser_channel="msedge",
    )
    scraper._proxy_runtime = FailingProxyRuntime()

    with pytest.raises(ManualActionRequiredError) as exc_info:
        asyncio.run(_open_only(scraper))

    assert exc_info.value.stage == "proxy_unavailable"
    assert "proxy" in exc_info.value.message.lower()
    assert chromium.launch_calls == []
    assert handle.stopped is True


def test_ctgoodjobs_fresh_profile_restarts_runtime_with_new_proxy_after_challenge(monkeypatch):
    first_page = FakePage(html="Just a moment", title_text="Just a moment")
    second_page = FakePage(html="<html>ok</html>", title_text="Recovered")
    contexts = [FakeContext([first_page]), FakeContext([second_page])]

    class SequencedChromium(FakeChromium):
        def launch_persistent_context(self, *, user_data_dir: str, **kwargs) -> FakeContext:
            self.launch_calls.append({"user_data_dir": user_data_dir, **kwargs})
            return contexts.pop(0)

    chromium = SequencedChromium()
    _install_fake_playwright(monkeypatch, chromium)

    class RotatingProxyRuntime:
        enabled = True

        def __init__(self) -> None:
            self.leases = [
                ProxyLease(proxy_url="http://proxy-a:8080", provider_name="static", identity="proxy-a"),
                ProxyLease(proxy_url="http://proxy-b:8080", provider_name="static", identity="proxy-b"),
            ]

        async def acquire_lease(self):
            return self.leases.pop(0)

        def build_playwright_proxy_config(self, lease):
            return {"server": lease.proxy_url}

        async def report_challenge(self, **_kwargs):
            return None

        async def report_success(self, **_kwargs):
            return None

        async def report_network_failure(self, **_kwargs):
            return None

    async def run_scraper() -> str:
        scraper = CTGoodJobsBrowserPageScraper(
            request_payload={"resume_strategy": "fresh_profile"},
            user_data_dir=r"C:\profiles\ctgoodjobs-rotating-proxy",
            browser_channel="msedge",
            max_attempts=2,
        )
        scraper._proxy_runtime = RotatingProxyRuntime()
        async with scraper:
            return await scraper.fetch_page_html(
                "https://jobs.ctgoodjobs.hk/job/1001",
                stage="detail_page",
            )

    html = asyncio.run(run_scraper())

    assert html == "<html>ok</html>"
    assert len(chromium.launch_calls) == 2
    assert chromium.launch_calls[0]["proxy"] == {"server": "http://proxy-a:8080"}
    assert chromium.launch_calls[1]["proxy"] == {"server": "http://proxy-b:8080"}


def test_ctgoodjobs_fresh_profile_restarts_runtime_with_new_proxy_after_network_failure(monkeypatch):
    class FailingGotoPage(FakePage):
        def __init__(self) -> None:
            super().__init__(html="<html>ok</html>", title_text="Recovered")
            self.fail_once = True

        def goto(self, url: str, *, wait_until: str, timeout: int | None = None):
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("proxy connection dropped")
            return super().goto(url, wait_until=wait_until, timeout=timeout)

    first_page = FailingGotoPage()
    second_page = FakePage(html="<html>ok</html>", title_text="Recovered")
    contexts = [FakeContext([first_page]), FakeContext([second_page])]

    class SequencedChromium(FakeChromium):
        def launch_persistent_context(self, *, user_data_dir: str, **kwargs) -> FakeContext:
            self.launch_calls.append({"user_data_dir": user_data_dir, **kwargs})
            return contexts.pop(0)

    chromium = SequencedChromium()
    _install_fake_playwright(monkeypatch, chromium)

    class RotatingProxyRuntime:
        enabled = True

        def __init__(self) -> None:
            self.leases = [
                ProxyLease(proxy_url="http://proxy-a:8080", provider_name="static", identity="proxy-a"),
                ProxyLease(proxy_url="http://proxy-b:8080", provider_name="static", identity="proxy-b"),
            ]

        async def acquire_lease(self):
            return self.leases.pop(0)

        def build_playwright_proxy_config(self, lease):
            return {"server": lease.proxy_url}

        async def report_challenge(self, **_kwargs):
            return None

        async def report_success(self, **_kwargs):
            return None

        async def report_network_failure(self, **_kwargs):
            return None

    async def run_scraper() -> str:
        scraper = CTGoodJobsBrowserPageScraper(
            request_payload={"resume_strategy": "fresh_profile"},
            user_data_dir=r"C:\profiles\ctgoodjobs-rotating-proxy-network",
            browser_channel="msedge",
            max_attempts=2,
        )
        scraper._proxy_runtime = RotatingProxyRuntime()
        async with scraper:
            return await scraper.fetch_page_html(
                "https://jobs.ctgoodjobs.hk/job/1002",
                stage="detail_page",
            )

    html = asyncio.run(run_scraper())

    assert html == "<html>ok</html>"
    assert len(chromium.launch_calls) == 2
    assert chromium.launch_calls[0]["proxy"] == {"server": "http://proxy-a:8080"}
    assert chromium.launch_calls[1]["proxy"] == {"server": "http://proxy-b:8080"}


def test_jobsdb_fresh_profile_converts_profile_in_use_launch_failure_into_manual_action_error(
    monkeypatch,
):
    chromium = FakeChromium(
        launch_exception=RuntimeError(
            "BrowserType.launch_persistent_context: Target page, context or browser has been closed"
        )
    )
    handle = _install_fake_playwright(monkeypatch, chromium)
    scraper = JobsDBBrowserDetailScraper(
        request_payload={"resume_strategy": "fresh_profile"},
        user_data_dir=r"C:\profiles\fresh-in-use",
        browser_channel="msedge",
    )

    with pytest.raises(ManualActionRequiredError) as exc_info:
        asyncio.run(_open_only(scraper))

    assert exc_info.value.stage == "browser_profile_in_use"
    assert exc_info.value.action_type == "close_browser_window"
    assert "Close all Edge windows" in exc_info.value.message
    assert handle.stopped is True


@pytest.mark.parametrize(
    "scraper_cls",
    [JobsDBBrowserDetailScraper, CTGoodJobsBrowserPageScraper],
)
def test_reuse_open_browser_raises_manual_action_error_when_registry_session_is_unavailable(
    monkeypatch,
    scraper_cls,
):
    chromium = FakeChromium()
    _install_fake_playwright(monkeypatch, chromium)
    monkeypatch.setattr(f"{scraper_cls.__module__}.get_live_browser_registry", lambda: LiveBrowserRegistry())

    with pytest.raises(ManualActionRequiredError, match="No reusable browser session is available"):
        asyncio.run(
            _open_and_close(
                scraper_cls(
                    request_payload={"resume_strategy": "reuse_open_browser"},
                    user_data_dir=r"C:\profiles\missing-session",
                    browser_channel="msedge",
                )
            )
        )

    assert chromium.connect_calls == []
    assert chromium.launch_calls == []


@pytest.mark.parametrize(
    "scraper_cls",
    [JobsDBBrowserDetailScraper, CTGoodJobsBrowserPageScraper],
)
def test_reuse_open_browser_converts_cdp_connect_failures_into_manual_action_error_and_cleans_up(
    monkeypatch,
    scraper_cls,
):
    profile_path = r"C:\profiles\stale-session"
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=profile_path,
        blocked_url="https://example.test/challenge",
        debug_port=46666,
    )
    chromium = FakeChromium(connect_exception=RuntimeError("CDP target unreachable"))
    handle = _install_fake_playwright(monkeypatch, chromium)
    monkeypatch.setattr(f"{scraper_cls.__module__}.get_live_browser_registry", lambda: registry)
    scraper = scraper_cls(
        request_payload={"resume_strategy": "reuse_open_browser"},
        user_data_dir=profile_path,
        browser_channel="msedge",
    )

    with pytest.raises(ManualActionRequiredError, match="The reusable browser session is unavailable"):
        asyncio.run(_open_only(scraper))

    assert chromium.connect_calls == ["http://127.0.0.1:46666"]
    assert handle.stopped is True
    assert scraper._executor is None
    assert scraper._sync_playwright is None
    assert scraper._sync_browser is None
    assert scraper._sync_context is None
    assert scraper._sync_page is None
    assert scraper._runtime_started is False


def test_ctgoodjobs_manual_action_instructions_do_not_tell_operator_to_close_browser():
    async def blocked_fetcher(url: str) -> str:
        return "<html><body>Just a moment...</body></html>"

    scraper = CTGoodJobsBrowserPageScraper(page_content_fetcher=blocked_fetcher, max_attempts=1)

    with pytest.raises(ManualActionRequiredError) as exc_info:
        asyncio.run(
            scraper.fetch_page_html(
                "https://example.test/challenge",
                stage="listing",
            )
        )

    instructions = exc_info.value.instructions
    assert any("keep the browser open" in instruction.lower() for instruction in instructions)
    assert all("close" not in instruction.lower() for instruction in instructions)


def test_capture_manual_action_screenshot_falls_back_cleanly_when_no_live_session_is_available(
    monkeypatch,
):
    chromium = FakeChromium(persistent_context=FakeContext([FakePage(screenshot_bytes=b"fallback-image")]))
    handle = _install_fake_playwright(monkeypatch, chromium)

    payload = capture_manual_action_screenshot(
        browser_channel="msedge",
        browser_profile_path=r"C:\profiles\missing-live-session",
        blocked_url="https://example.test/challenge",
        crawl_job_id=uuid4(),
        resume_strategy="reuse_open_browser",
        live_browser_registry=LiveBrowserRegistry(),
        session_reachability_probe=lambda session: True,
    )

    assert chromium.connect_calls == []
    assert len(chromium.launch_calls) == 1
    assert base64.b64decode(payload["image_base64"]) == b"fallback-image"
    assert chromium.persistent_context.closed is True
    assert handle.stopped is True


def test_capture_manual_action_screenshot_reuses_live_session_without_closing_visible_browser(
    monkeypatch,
):
    registry = LiveBrowserRegistry()
    profile_path = r"C:\profiles\visible-browser"
    registry.register(
        browser_channel="msedge",
        browser_profile_path=profile_path,
        blocked_url="https://example.test/challenge",
        debug_port=47777,
    )
    existing_page = FakePage(screenshot_bytes=b"live-image")
    attached_context = FakeContext([existing_page])
    attached_browser = FakeBrowser([attached_context])
    chromium = FakeChromium(browser=attached_browser)
    handle = _install_fake_playwright(monkeypatch, chromium)

    payload = capture_manual_action_screenshot(
        browser_channel="msedge",
        browser_profile_path=profile_path,
        blocked_url="https://example.test/challenge",
        crawl_job_id=uuid4(),
        resume_strategy="reuse_open_browser",
        live_browser_registry=registry,
        session_reachability_probe=lambda session: True,
    )

    assert chromium.connect_calls == ["http://127.0.0.1:47777"]
    assert chromium.launch_calls == []
    assert base64.b64decode(payload["image_base64"]) == b"live-image"
    assert attached_context.closed is False
    assert attached_browser.closed is False
    assert handle.stopped is True


def test_capture_manual_action_screenshot_logs_attach_failure_and_fallback_with_job_id_and_strategy(
    monkeypatch,
    caplog,
):
    registry = LiveBrowserRegistry()
    profile_path = r"C:\profiles\stale-live-session"
    crawl_job_id = uuid4()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=profile_path,
        blocked_url="https://example.test/challenge",
        debug_port=48888,
    )
    chromium = FakeChromium(
        persistent_context=FakeContext([FakePage(screenshot_bytes=b"fallback-after-attach-failure")]),
        connect_exception=RuntimeError("CDP unreachable"),
    )
    handle = _install_fake_playwright(monkeypatch, chromium)

    with caplog.at_level(logging.INFO):
        payload = capture_manual_action_screenshot(
            browser_channel="msedge",
            browser_profile_path=profile_path,
            blocked_url="https://example.test/challenge",
            crawl_job_id=crawl_job_id,
            resume_strategy="reuse_open_browser",
            live_browser_registry=registry,
            session_reachability_probe=lambda session: True,
        )

    assert chromium.connect_calls == ["http://127.0.0.1:48888"]
    assert len(chromium.launch_calls) == 1
    assert base64.b64decode(payload["image_base64"]) == b"fallback-after-attach-failure"
    assert handle.stopped is True

    attach_attempt_log = next(record for record in caplog.records if record.message == "manual_action_screenshot_attach_attempt")
    attach_failure_log = next(record for record in caplog.records if record.message == "manual_action_screenshot_attach_failure")
    fallback_log = next(record for record in caplog.records if record.message == "manual_action_screenshot_fallback_selected")

    assert str(attach_attempt_log.crawl_job_id) == str(crawl_job_id)
    assert attach_attempt_log.strategy == "reuse_open_browser"
    assert str(attach_failure_log.crawl_job_id) == str(crawl_job_id)
    assert attach_failure_log.strategy == "reuse_open_browser"
    assert str(fallback_log.crawl_job_id) == str(crawl_job_id)
    assert fallback_log.strategy == "reuse_open_browser"
