from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.browser_launch import launch_persistent_context_with_fallback
from app.scraper.access_block import classify_public_access_evidence
from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL
from app.scraper.ctgoodjobs.html_fetcher import CTGoodJobsFetchError, looks_like_interstitial_html
from app.scraper.ctgoodjobs.page_state import (
    CTGoodJobsTerminalUnavailableError,
    classify_ctgoodjobs_detail_page,
)
from app.scraper.proxy_rotation import build_ctgoodjobs_proxy_runtime
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    build_session_recovery_manual_action,
    resolve_manual_action_cdp_connect_host,
)
from app.utils.anti_detection import ExponentialBackoff


PageContentFetcher = Callable[[str], Awaitable[str]]
SyncPageContentFetcher = Callable[[str], str]

logger = logging.getLogger(__name__)

HEADED_DISPLAY_UNAVAILABLE_MARKERS = (
    "without having a XServer running",
    "Missing X server or $DISPLAY",
    "use 'xvfb-run",
)


class CTGoodJobsBrowserPageScraper:
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
        max_attempts: int = 3,
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
        self.max_attempts = max(1, int(max_attempts))
        self._executor: ThreadPoolExecutor | None = None
        self._runtime_started = False
        self._sync_playwright = None
        self._sync_browser = None
        self._sync_context = None
        self._sync_page = None
        self._last_page_title: str | None = None
        self._last_page_url: str | None = None
        self._last_response_status: int | None = None
        self._proxy_runtime = build_ctgoodjobs_proxy_runtime(settings_source=settings)
        self._proxy_lease = None

    async def __aenter__(self):
        if self.page_content_fetcher is None and self.sync_page_content_fetcher is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctgoodjobs-headed")
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._executor, self._start_sync_runtime)
            except Exception as exc:
                await self._cleanup_failed_startup(loop)
                if self.resume_strategy == RESUME_STRATEGY_FRESH_PROFILE:
                    self._raise_if_headed_display_unavailable(exc)
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

    async def fetch_page_html(
        self,
        url: str,
        *,
        stage: str,
        referer: str | None = None,
    ) -> str:
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=8.0, max_retries=self.max_attempts, jitter=0.25)

        for attempt in range(self.max_attempts):
            try:
                html = await self._fetch_page_content(url)
                access_evidence = classify_public_access_evidence(
                    status_code=self._last_response_status,
                    final_url=self._last_page_url or url,
                    title=self._last_page_title,
                    text=html if len(html) <= 65536 else html[:4096],
                )
                if (
                    access_evidence is not None
                    and access_evidence.classification == "ip_blocked"
                ):
                    if self._proxy_runtime.enabled:
                        await self._proxy_runtime.report_challenge(
                            stage=stage,
                            lease=self._proxy_lease,
                        )
                    logger.warning(
                        "SCRAPE_FETCH_MANUAL_ACTION source=ctgoodjobs "
                        "crawl_job_id=%s stage=%s classification=ip_blocked "
                        "status_code=%s reason=%s",
                        self.request_payload.get("crawl_job_id"),
                        stage,
                        access_evidence.status_code,
                        access_evidence.reason,
                    )
                    raise build_session_recovery_manual_action(
                        source_site="ctgoodjobs",
                        stage=stage,
                        blocked_url=access_evidence.final_url or url,
                        referer=referer,
                        classification="ip_blocked",
                        evidence=access_evidence.to_payload(),
                    )
                if self._looks_like_interstitial(html):
                    if self._proxy_runtime.enabled:
                        await self._proxy_runtime.report_challenge(
                            stage=stage,
                            lease=self._proxy_lease,
                        )
                    challenge_evidence = (
                        access_evidence.to_payload()
                        if access_evidence
                        else {
                            "final_url": self._last_page_url or url,
                            "status_code": self._last_response_status,
                            "reason": "interstitial_marker",
                        }
                    )
                    logger.warning(
                        "SCRAPE_FETCH_MANUAL_ACTION source=ctgoodjobs crawl_job_id=%s "
                        "stage=%s classification=waf_challenge reason=%s",
                        self.request_payload.get("crawl_job_id"),
                        stage,
                        challenge_evidence.get("reason"),
                    )
                    raise build_session_recovery_manual_action(
                        source_site="ctgoodjobs",
                        stage=stage,
                        blocked_url=self._last_page_url or url,
                        referer=referer,
                        classification="waf_challenge",
                        evidence=challenge_evidence,
                    )
                if stage == "detail_page":
                    unavailable_evidence = classify_ctgoodjobs_detail_page(
                        status_code=self._last_response_status,
                        final_url=self._last_page_url or url,
                        title=self._last_page_title,
                        html=html,
                    )
                    if unavailable_evidence is not None:
                        raise CTGoodJobsTerminalUnavailableError.from_evidence(
                            unavailable_evidence
                        )
                if self._proxy_runtime.enabled:
                    await self._proxy_runtime.report_success(
                        stage=stage,
                        lease=self._proxy_lease,
                    )
                return html
            except (
                CTGoodJobsFetchError,
                CTGoodJobsTerminalUnavailableError,
                ManualActionRequiredError,
            ):
                raise
            except Exception as exc:
                if self._proxy_runtime.enabled:
                    await self._proxy_runtime.report_network_failure(
                        stage=stage,
                        lease=self._proxy_lease,
                    )
                if attempt == self.max_attempts - 1:
                    raise CTGoodJobsFetchError(
                        stage=stage,
                        url=url,
                        attempts=attempt + 1,
                        exception_type=type(exc).__name__,
                    ) from exc
                await self._reset_runtime_for_retry()
                await backoff.wait(attempt)

        raise AssertionError("unreachable")

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
                "source_site": "ctgoodjobs",
            },
        )

        launch_kwargs = {
            "headless": False,
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        else:
            launch_kwargs["channel"] = self.browser_channel
        if self._proxy_runtime.enabled:
            try:
                self._proxy_lease = asyncio.run(self._proxy_runtime.acquire_lease())
            except Exception as exc:
                self._raise_if_proxy_unavailable(exc)
                raise
            proxy_config = self._proxy_runtime.build_playwright_proxy_config(self._proxy_lease)
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config

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
                "ctgoodjobs_browser_channel_fallback requested=%s resolved=%s crawl_job_id=%s",
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
            "manual_action_attach_attempt",
            extra={
                "crawl_job_id": self.request_payload.get("crawl_job_id"),
                "strategy": self.resume_strategy,
                "source_site": "ctgoodjobs",
                "cdp_host": cdp_host,
                "cdp_connect_host": cdp_connect_host,
                "debug_port": session.debug_port,
            },
        )
        try:
            self._sync_browser = self._sync_playwright.chromium.connect_over_cdp(
                f"http://{cdp_connect_host}:{session.debug_port}"
            )
        except ManualActionRequiredError:
            raise
        except Exception as exc:
            logger.info(
                "manual_action_attach_failure",
                extra={
                    "crawl_job_id": self.request_payload.get("crawl_job_id"),
                    "strategy": self.resume_strategy,
                    "source_site": "ctgoodjobs",
                    "cdp_host": cdp_host,
                    "cdp_connect_host": cdp_connect_host,
                    "debug_port": session.debug_port,
                    "error": str(exc),
                },
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message="The reusable browser session is unavailable. Reopen the manual browser or choose Fresh Profile."
            ) from exc
        self._sync_context = self._sync_browser.contexts[0] if self._sync_browser.contexts else None
        if self._sync_context is None:
            logger.info(
                "manual_action_attach_failure",
                extra={
                    "crawl_job_id": self.request_payload.get("crawl_job_id"),
                    "strategy": self.resume_strategy,
                    "source_site": "ctgoodjobs",
                    "cdp_host": cdp_host,
                    "cdp_connect_host": cdp_connect_host,
                    "debug_port": session.debug_port,
                    "error": "Attached browser exposes no reusable context",
                },
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message="The reusable browser session is unavailable. Reopen the manual browser or choose Fresh Profile."
            )

        self._sync_context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._sync_page = self._sync_context.pages[0] if self._sync_context.pages else self._sync_context.new_page()
        self._sync_page.wait_for_timeout(1500)
        logger.info(
            "manual_action_attach_success",
            extra={
                "crawl_job_id": self.request_payload.get("crawl_job_id"),
                "strategy": self.resume_strategy,
                "source_site": "ctgoodjobs",
                "cdp_host": cdp_host,
                "cdp_connect_host": cdp_connect_host,
                "debug_port": session.debug_port,
            },
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
        self._proxy_lease = None

    async def _cleanup_failed_startup(self, loop) -> None:
        if self._executor is None:
            return
        try:
            await loop.run_in_executor(self._executor, self._stop_sync_runtime)
        finally:
            self._executor.shutdown(wait=True)
            self._executor = None

    async def _reset_runtime_for_retry(self) -> None:
        if (
            self.resume_strategy != RESUME_STRATEGY_FRESH_PROFILE
            or not self._proxy_runtime.enabled
            or not self._runtime_started
            or self._executor is None
        ):
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._stop_sync_runtime)

    def _build_reuse_open_browser_unavailable_error(self, *, message: str) -> ManualActionRequiredError:
        return ManualActionRequiredError(
            source_site="ctgoodjobs",
            stage="reuse_open_browser_unavailable",
            blocked_url=f"{CTGOODJOBS_BASE_URL}/jobs",
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
        return looks_like_interstitial_html(html) or self._response_indicates_cloudflare_challenge(html)

    def _response_indicates_cloudflare_challenge(self, html: str) -> bool:
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

    def _raise_if_headed_display_unavailable(self, exc: Exception) -> None:
        message = str(exc or "")
        if not any(marker in message for marker in HEADED_DISPLAY_UNAVAILABLE_MARKERS):
            return

        logger.warning(
            "ctgoodjobs_headed_display_unavailable crawl_job_id=%s user_data_dir=%s error=%s",
            self.request_payload.get("crawl_job_id"),
            self._resolve_user_data_dir(),
            message.splitlines()[0] if message else type(exc).__name__,
        )
        raise ManualActionRequiredError(
            source_site="ctgoodjobs",
            stage="headed_display_unavailable",
            blocked_url=f"{CTGOODJOBS_BASE_URL}/jobs",
            message=(
                "CTGoodJobs headed browser could not start because this runtime has no X server/$DISPLAY. "
                "Start the host-side headed worker or run the crawl from a desktop session, then resume."
            ),
            action_type="environment_setup",
            instructions=[
                "Start the host-side headed worker or run the backend in a desktop session with display support.",
                "Retry the crawl after headed browser launch is available in this runtime.",
            ],
        ) from exc

    def _raise_if_profile_in_use(self, exc: Exception) -> None:
        message = str(exc or "")
        if any(marker in message for marker in HEADED_DISPLAY_UNAVAILABLE_MARKERS):
            return
        if "launch_persistent_context" not in message or "Target page, context or browser has been closed" not in message:
            return

        logger.warning(
            "ctgoodjobs_browser_profile_in_use crawl_job_id=%s user_data_dir=%s error=%s",
            self.request_payload.get("crawl_job_id"),
            self._resolve_user_data_dir(),
            message.splitlines()[0] if message else type(exc).__name__,
        )
        raise ManualActionRequiredError(
            source_site="ctgoodjobs",
            stage="browser_profile_in_use",
            blocked_url=f"{CTGOODJOBS_BASE_URL}/jobs",
            message="Close all Edge windows using the automation profile, then click Resume.",
            action_type="close_browser_window",
            instructions=[
                "Close all Edge windows that use the listed automation profile.",
                "Return to the app and click Resume.",
            ],
        ) from exc

    def _raise_if_proxy_unavailable(self, exc: Exception) -> None:
        message = str(exc or "")
        if "Unable to acquire a usable CTGoodJobs proxy lease" not in message:
            return

        raise ManualActionRequiredError(
            source_site="ctgoodjobs",
            stage="proxy_unavailable",
            blocked_url=f"{CTGOODJOBS_BASE_URL}/jobs",
            message="No usable CTGoodJobs proxy lease is available. Check the proxy configuration or try again later.",
            instructions=[
                "Verify the CTGoodJobs proxy settings and provider availability.",
                "If you are using a pool, wait for a healthy lease or relax the filtering requirements.",
                "Return to the app and click Resume after proxy availability is restored.",
            ],
        ) from exc

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)

        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / self.browser_channel

        return Path(".playwright") / self.browser_channel
