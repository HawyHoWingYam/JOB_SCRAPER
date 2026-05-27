from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL
from app.scraper.ctgoodjobs.html_fetcher import CTGoodJobsFetchError, looks_like_interstitial_html
from app.scraper.manual_action import ManualActionRequiredError
from app.utils.anti_detection import ExponentialBackoff


PageContentFetcher = Callable[[str], Awaitable[str]]
SyncPageContentFetcher = Callable[[str], str]


class CTGoodJobsBrowserPageScraper:
    def __init__(
        self,
        *,
        page_content_fetcher: PageContentFetcher | None = None,
        sync_page_content_fetcher: SyncPageContentFetcher | None = None,
        browser_channel: str | None = None,
        user_data_dir: str | None = None,
        executable_path: str | None = None,
        navigation_timeout_ms: int | None = None,
        max_attempts: int = 3,
    ):
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
        self._sync_context = None
        self._sync_page = None

    async def __aenter__(self):
        if self.page_content_fetcher is None and self.sync_page_content_fetcher is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ctgoodjobs-headed")
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._executor, self._start_sync_runtime)
            except Exception as exc:
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
                if self._looks_like_interstitial(html):
                    if attempt == self.max_attempts - 1:
                        raise ManualActionRequiredError(
                            source_site="ctgoodjobs",
                            stage=stage,
                            blocked_url=url,
                            referer=referer,
                            message=f"CTGoodJobs {stage} fetch blocked by human verification",
                            instructions=[
                                "Open Edge using the listed profile.",
                                "Visit the blocked URL and complete the verification challenge.",
                                "Close the manual browser window.",
                                "Return to the app and click Resume.",
                            ],
                        )
                    await backoff.wait(attempt)
                    continue
                return html
            except (CTGoodJobsFetchError, ManualActionRequiredError):
                raise
            except Exception as exc:
                if attempt == self.max_attempts - 1:
                    raise CTGoodJobsFetchError(
                        stage=stage,
                        url=url,
                        attempts=attempt + 1,
                        exception_type=type(exc).__name__,
                    ) from exc
                await backoff.wait(attempt)

        raise AssertionError("unreachable")

    async def _fetch_page_content(self, url: str) -> str:
        if self.page_content_fetcher is not None:
            return await self.page_content_fetcher(url)
        fetcher = self.sync_page_content_fetcher or self._fetch_page_content_sync
        if self._executor is None:
            return await asyncio.to_thread(fetcher, url)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fetcher, url)

    def _start_sync_runtime(self) -> None:
        if self._runtime_started:
            return

        from playwright.sync_api import sync_playwright

        self._sync_playwright = sync_playwright().start()
        launch_kwargs = {
            "headless": False,
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        else:
            launch_kwargs["channel"] = self.browser_channel

        self._sync_context = self._sync_playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._resolve_user_data_dir()),
            **launch_kwargs,
        )
        self._sync_context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._sync_page = self._sync_context.pages[0] if self._sync_context.pages else self._sync_context.new_page()
        self._runtime_started = True

    def _stop_sync_runtime(self) -> None:
        if self._sync_context is not None:
            self._sync_context.close()
        if self._sync_playwright is not None:
            self._sync_playwright.stop()
        self._sync_page = None
        self._sync_context = None
        self._sync_playwright = None
        self._runtime_started = False

    def _fetch_page_content_sync(self, url: str) -> str:
        if not self._runtime_started:
            self._start_sync_runtime()
        self._sync_page.goto(url, wait_until="domcontentloaded")
        self._sync_page.wait_for_timeout(3000)
        return self._sync_page.content()

    def _looks_like_interstitial(self, html: str) -> bool:
        return looks_like_interstitial_html(html)

    def _raise_if_profile_in_use(self, exc: Exception) -> None:
        message = str(exc or "")
        if "launch_persistent_context" not in message or "Target page, context or browser has been closed" not in message:
            return

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

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)

        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / self.browser_channel

        return Path(".playwright") / self.browser_channel
