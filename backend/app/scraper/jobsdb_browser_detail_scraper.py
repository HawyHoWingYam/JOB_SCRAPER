from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.scraper.manual_action import ManualActionRequiredError
from app.sources.jobsdb.parsers import parse_detail_page as parse_jobsdb_detail_page


PageContentFetcher = Callable[[str], Awaitable[str]]
SyncPageContentFetcher = Callable[[str], str]


class JobsDBBrowserDetailScraper:
    def __init__(
        self,
        *,
        page_content_fetcher: PageContentFetcher | None = None,
        sync_page_content_fetcher: SyncPageContentFetcher | None = None,
        browser_channel: str | None = None,
        user_data_dir: str | None = None,
        executable_path: str | None = None,
        navigation_timeout_ms: int | None = None,
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
        self._executor: ThreadPoolExecutor | None = None
        self._runtime_started = False
        self._sync_playwright = None
        self._sync_context = None
        self._sync_page = None

    async def __aenter__(self):
        if self.page_content_fetcher is None and self.sync_page_content_fetcher is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jobsdb-headed")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._start_sync_runtime)
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
        html = await self._fetch_page_content(url)
        if self._looks_like_interstitial(html):
            raise ManualActionRequiredError(
                source_site="jobsdb",
                stage="detail_page",
                blocked_url=url,
                referer=settings.jobsdb_base_url,
                message="JobsDB detail fetch blocked by human verification",
                instructions=[
                    "Open the headed browser profile.",
                    "Complete the human verification challenge.",
                    "Return to the app and click Resume.",
                ],
            )
        return parse_jobsdb_detail_page(html, job_id=job_id)

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
        lowered = (html or "").lower()
        return "just a moment" in lowered or "cf-challenge" in lowered or "challenges.cloudflare.com" in lowered

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)

        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / self.browser_channel

        return Path(".playwright") / self.browser_channel
