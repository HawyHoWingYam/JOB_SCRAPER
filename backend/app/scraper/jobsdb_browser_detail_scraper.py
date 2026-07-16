from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.access_block import classify_public_access_evidence
from app.scraper.browser_launch import launch_persistent_context_with_fallback
from app.scraper.log_events import build_scrape_log_event
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    build_session_recovery_manual_action,
    resolve_manual_action_cdp_connect_host,
)
from app.sources.jobsdb.parsers import parse_detail_page as parse_jobsdb_detail_page


PageContentFetcher = Callable[[str], Awaitable[str]]
SyncPageContentFetcher = Callable[[str], str]

logger = logging.getLogger(__name__)


class JobsDBBrowserDetailScraper:
    def __init__(
        self,
        *,
        request_payload: dict | None = None,
        page_content_fetcher: PageContentFetcher | None = None,
        sync_page_content_fetcher: SyncPageContentFetcher | None = None,
        browser_channel: str | None = None,
        user_data_dir: str | None = None,
        executable_path: str | None = None,
        navigation_timeout_ms: int | None = None,
    ):
        self.request_payload = dict(request_payload or {})
        self.resume_strategy = self.request_payload.get("resume_strategy") or RESUME_STRATEGY_FRESH_PROFILE
        self.page_content_fetcher = page_content_fetcher
        self.sync_page_content_fetcher = sync_page_content_fetcher
        self.browser_channel = browser_channel or settings.jobsdb_headed_browser_channel
        self.user_data_dir = user_data_dir or settings.jobsdb_headed_browser_user_data_dir
        self.executable_path = executable_path or settings.jobsdb_headed_browser_executable_path
        self.navigation_timeout_ms = (
            navigation_timeout_ms
            if navigation_timeout_ms is not None
            else settings.jobsdb_headed_navigation_timeout_ms
        )
        self._executor: ThreadPoolExecutor | None = None
        self._runtime_started = False
        self._sync_playwright = None
        self._sync_browser = None
        self._sync_context = None
        self._sync_page = None
        self._last_page_title: str | None = None
        self._last_page_url: str | None = None
        self._last_response_status: int | None = None

    async def __aenter__(self):
        if self.page_content_fetcher is None and self.sync_page_content_fetcher is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jobsdb-headed")
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._executor, self._start_sync_runtime)
            except Exception as exc:
                await self._cleanup_failed_startup(loop)
                if self.resume_strategy == RESUME_STRATEGY_FRESH_PROFILE:
                    self._raise_if_profile_in_use(exc)
                raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._executor is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._executor, self._stop_sync_runtime)
            finally:
                self._executor.shutdown(wait=True)
                self._executor = None
        return None

    async def fetch_job_detail(self, job_id: str, client=None) -> dict | None:
        url = f"https://hk.jobsdb.com/job/{job_id}"
        logger.debug(
            build_scrape_log_event(
                "SCRAPE_DETAIL_START",
                source="jobsdb",
                crawl_job_id=self.request_payload.get("crawl_job_id"),
                source_job_id=job_id,
                url=url,
            )
        )
        html = await self._fetch_page_content(url)
        access_evidence = classify_public_access_evidence(
            status_code=self._last_response_status,
            final_url=self._last_page_url or url,
            title=self._last_page_title,
            text=html if len(html) <= 65536 else html[:4096],
        )
        if access_evidence is not None or self._looks_like_interstitial(html):
            classification = (
                access_evidence.classification
                if access_evidence is not None
                else "waf_challenge"
            )
            evidence = (
                access_evidence.to_payload()
                if access_evidence is not None
                else {
                    "status_code": self._last_response_status,
                    "final_url": self._last_page_url or url,
                    "reason": "interstitial_marker",
                }
            )
            logger.warning(
                build_scrape_log_event(
                    "SCRAPE_DETAIL_MANUAL_ACTION",
                    source="jobsdb",
                    crawl_job_id=self.request_payload.get("crawl_job_id"),
                    source_job_id=job_id,
                    url=url,
                    classification=classification,
                    status_code=self._last_response_status,
                    reason=evidence.get("reason"),
                )
            )
            raise build_session_recovery_manual_action(
                source_site="jobsdb",
                stage="detail_page",
                blocked_url=self._last_page_url or url,
                referer=settings.jobsdb_base_url,
                classification=classification,
                evidence=evidence,
            )
        detail = parse_jobsdb_detail_page(html, job_id=job_id)
        logger.debug(
            build_scrape_log_event(
                "SCRAPE_DETAIL_OK",
                source="jobsdb",
                crawl_job_id=self.request_payload.get("crawl_job_id"),
                source_job_id=job_id,
                url=url,
            )
        )
        return detail

    async def _fetch_page_content(self, url: str) -> str:
        if self.page_content_fetcher is not None:
            self._last_response_status = None
            self._last_page_title = None
            self._last_page_url = url
            return await self.page_content_fetcher(url)
        fetcher = self.sync_page_content_fetcher or self._fetch_page_content_sync
        if self._executor is None:
            self._last_response_status = None
            self._last_page_title = None
            self._last_page_url = url
            return await asyncio.to_thread(fetcher, url)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fetcher, url)

    def _start_sync_runtime(self) -> None:
        if self._runtime_started:
            return

        from playwright.sync_api import sync_playwright

        self._sync_playwright = sync_playwright().start()
        if self.resume_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
            self._attach_to_live_browser()
            self._runtime_started = True
            return
        logger.info(
            "manual_action_fresh_resume_selected",
            extra={
                "crawl_job_id": self.request_payload.get("crawl_job_id"),
                "strategy": self.resume_strategy,
                "source_site": "jobsdb",
            },
        )

        launch_kwargs = {
            "headless": False,
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        else:
            launch_kwargs["channel"] = self.browser_channel

        launch_result = launch_persistent_context_with_fallback(
            self._sync_playwright.chromium,
            user_data_dir=str(self._resolve_user_data_dir()),
            browser_channel=self.browser_channel,
            executable_path=self.executable_path,
            headless=False,
            extra_launch_kwargs={
                key: value for key, value in launch_kwargs.items() if key != "headless"
            },
        )
        if launch_result.attempted_fallback:
            logger.warning(
                "jobsdb_browser_channel_fallback requested=%s resolved=%s crawl_job_id=%s",
                launch_result.requested_channel,
                launch_result.resolved_channel,
                self.request_payload.get("crawl_job_id"),
            )
        self._sync_context = launch_result.context
        self._sync_context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._sync_page = self._sync_context.pages[0] if self._sync_context.pages else self._sync_context.new_page()
        self._runtime_started = True

    def _attach_to_live_browser(self) -> None:
        session = get_live_browser_registry().get(str(self._resolve_user_data_dir()))
        if session is None or int(session.debug_port or 0) <= 0:
            raise self._build_reuse_open_browser_unavailable_error(
                message="No reusable browser session is available for this automation profile. Open the manual browser again or choose Fresh Profile."
            )
        cdp_host = settings.manual_action_cdp_host or settings.manual_action_helper_host
        cdp_connect_host = resolve_manual_action_cdp_connect_host(cdp_host)

        logger.info(
            build_scrape_log_event(
                "manual_action_attach_attempt",
                source="jobsdb",
                crawl_job_id=self.request_payload.get("crawl_job_id"),
                strategy=self.resume_strategy,
                cdp_host=cdp_host,
                cdp_connect_host=cdp_connect_host,
                debug_port=session.debug_port,
            )
        )
        try:
            self._sync_browser = self._sync_playwright.chromium.connect_over_cdp(
                f"http://{cdp_connect_host}:{session.debug_port}"
            )
        except ManualActionRequiredError:
            raise
        except Exception as exc:
            logger.info(
                build_scrape_log_event(
                    "manual_action_attach_failure",
                    source="jobsdb",
                    crawl_job_id=self.request_payload.get("crawl_job_id"),
                    strategy=self.resume_strategy,
                    cdp_host=cdp_host,
                    cdp_connect_host=cdp_connect_host,
                    debug_port=session.debug_port,
                    error_type=type(exc).__name__,
                )
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message="The reusable browser session is unavailable. Reopen the manual browser or choose Fresh Profile."
            ) from exc
        self._sync_context = self._sync_browser.contexts[0] if self._sync_browser.contexts else None
        if self._sync_context is None:
            logger.info(
                build_scrape_log_event(
                    "manual_action_attach_failure",
                    source="jobsdb",
                    crawl_job_id=self.request_payload.get("crawl_job_id"),
                    strategy=self.resume_strategy,
                    cdp_host=cdp_host,
                    cdp_connect_host=cdp_connect_host,
                    debug_port=session.debug_port,
                    reason="attached_browser_has_no_context",
                )
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message="The reusable browser session is unavailable. Reopen the manual browser or choose Fresh Profile."
            )

        self._sync_context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._sync_page = self._sync_context.pages[0] if self._sync_context.pages else self._sync_context.new_page()
        self._sync_page.wait_for_timeout(1500)
        logger.info(
            build_scrape_log_event(
                "manual_action_attach_success",
                source="jobsdb",
                crawl_job_id=self.request_payload.get("crawl_job_id"),
                strategy=self.resume_strategy,
                cdp_host=cdp_host,
                cdp_connect_host=cdp_connect_host,
                debug_port=session.debug_port,
            )
        )

    def _stop_sync_runtime(self) -> None:
        if self._sync_browser is None and self._sync_context is not None:
            self._sync_context.close()
        if self._sync_playwright is not None:
            self._sync_playwright.stop()
        self._sync_page = None
        self._sync_context = None
        self._sync_browser = None
        self._sync_playwright = None
        self._runtime_started = False
        self._last_page_title = None
        self._last_page_url = None
        self._last_response_status = None

    async def _cleanup_failed_startup(self, loop) -> None:
        if self._executor is None:
            return
        try:
            await loop.run_in_executor(self._executor, self._stop_sync_runtime)
        finally:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _build_reuse_open_browser_unavailable_error(self, *, message: str) -> ManualActionRequiredError:
        return ManualActionRequiredError(
            source_site="jobsdb",
            stage="reuse_open_browser_unavailable",
            blocked_url=settings.jobsdb_base_url,
            message=message,
            instructions=[
                "Reopen the visible browser for this automation profile and try Reuse Open Browser again.",
                "If no visible browser is available, resume with Fresh Profile instead.",
            ],
        )

    def _fetch_page_content_sync(self, url: str) -> str:
        if not self._runtime_started:
            self._start_sync_runtime()
        response = self._sync_page.goto(url, wait_until="domcontentloaded")
        self._sync_page.wait_for_timeout(3000)
        response_status = getattr(response, "status", None)
        self._last_response_status = (
            response_status if type(response_status) is int else None
        )
        self._last_page_title = self._sync_page.title()
        self._last_page_url = str(getattr(self._sync_page, "url", url) or url)
        return self._sync_page.content()

    def _looks_like_interstitial(self, html: str) -> bool:
        lowered_html = (html or "").lower()
        lowered_title = str(self._last_page_title or "").lower()
        lowered_url = str(self._last_page_url or "").lower()
        challenge_markers = (
            "just a moment",
            "cf-challenge",
            "challenges.cloudflare.com",
            "/cdn-cgi/challenge-platform",
            "challenge-platform",
            "__cf_chl_",
        )
        return any(
            marker in lowered_html or marker in lowered_title or marker in lowered_url
            for marker in challenge_markers
        )

    def _raise_if_profile_in_use(self, exc: Exception) -> None:
        message = str(exc or "")
        if "launch_persistent_context" not in message or "Target page, context or browser has been closed" not in message:
            return

        raise ManualActionRequiredError(
            source_site="jobsdb",
            stage="browser_profile_in_use",
            blocked_url=settings.jobsdb_base_url,
            message="Close all Edge windows using the automation profile, then click Resume.",
            action_type="close_browser_window",
            instructions=[
                "Close all Edge windows that use the listed automation profile.",
                "Return to the app and click Resume.",
            ],
        ) from exc

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)

        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / self.browser_channel

        return Path(".playwright") / self.browser_channel
