from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_BASE_URL,
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_SEARCH_URL,
)


_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"
_OFFERTODAY_DETAIL_URL_TEMPLATE = (
    f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"
)


@dataclass(slots=True)
class OfferTodaySessionCheckResult:
    current_url: str
    is_waf_challenge: bool
    listing_probe_payload: dict[str, Any] | None
    listing_result_count: int


class OfferTodayBrowserRuntime:
    def __init__(
        self,
        *,
        headed: bool = True,
        auth_state_path: str | None = None,
        resume_strategy: str = RESUME_STRATEGY_FRESH_PROFILE,
        browser_channel: str | None = None,
        user_data_dir: str | None = None,
        executable_path: str | None = None,
        navigation_timeout_ms: int | None = None,
    ) -> None:
        self.headed = headed
        self.auth_state_path = auth_state_path
        self.resume_strategy = resume_strategy or RESUME_STRATEGY_FRESH_PROFILE
        self.browser_channel = browser_channel or settings.offertoday_headed_browser_channel
        self.user_data_dir = user_data_dir or settings.offertoday_headed_browser_user_data_dir
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
        self._owns_context = False
        self._owns_browser = False
        self._runtime_started = False

    async def __aenter__(self) -> "OfferTodayBrowserRuntime":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()
        return None

    @staticmethod
    def is_waf_challenge_url(url: str | None) -> bool:
        return _WAF_CHALLENGE_PATH in str(url or "")

    async def start(self) -> None:
        if self._runtime_started:
            return

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            if self.resume_strategy == RESUME_STRATEGY_REUSE_OPEN_BROWSER:
                await self._attach_to_live_browser()
            else:
                await self._launch_fresh_profile()
            await self._warmup_page()
        except Exception:
            await self.stop()
            raise
        self._runtime_started = True

    async def stop(self) -> None:
        try:
            if self._owns_context and self._context is not None:
                await self._context.close()
            if self._owns_browser and self._browser is not None:
                await self._browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._owns_context = False
        self._owns_browser = False
        self._runtime_started = False

    async def fetch_listing_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return await self._fetch_json(
            OFFERTODAY_LISTING_SEARCH_URL,
            method="POST",
            payload=payload,
        )

    async def fetch_detail_json(
        self,
        *,
        job_id: str,
        encrypted_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        resolved_job_id = str(job_id or "").strip()
        resolved_encrypted_job_id = str(encrypted_job_id or resolved_job_id).strip()
        if not resolved_job_id or not resolved_encrypted_job_id:
            return None
        return await self._fetch_json(
            _OFFERTODAY_DETAIL_URL_TEMPLATE % (resolved_job_id, resolved_encrypted_job_id),
            method="GET",
        )

    async def check_session(
        self,
        *,
        listing_payload: dict[str, Any] | None = None,
    ) -> OfferTodaySessionCheckResult:
        probe_payload = await self.fetch_listing_json(
            listing_payload or {"keyword": "", "page": 1, "pageSize": 1}
        )
        result_list = (((probe_payload or {}).get("data") or {}).get("resultList") or [])
        listing_result_count = len(result_list) if isinstance(result_list, list) else 0
        current_url = str(getattr(self._page, "url", "") or "")
        return OfferTodaySessionCheckResult(
            current_url=current_url,
            is_waf_challenge=self.is_waf_challenge_url(current_url),
            listing_probe_payload=probe_payload,
            listing_result_count=listing_result_count,
        )

    async def _launch_fresh_profile(self) -> None:
        if not self.headed:
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
            )
            context_kwargs: dict[str, Any] = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                ),
                "locale": "zh-HK",
            }
            if self.auth_state_path:
                auth_path = Path(self.auth_state_path).resolve()
                if auth_path.exists():
                    context_kwargs["storage_state"] = str(auth_path)
            self._context = await self._browser.new_context(**context_kwargs)
            self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._owns_context = True
            self._owns_browser = True
            return

        launch_kwargs: dict[str, Any] = {"headless": False}
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        else:
            launch_kwargs["channel"] = self.browser_channel
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._resolve_user_data_dir()),
            **launch_kwargs,
        )
        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._owns_context = True
        self._owns_browser = False

    async def _attach_to_live_browser(self) -> None:
        session = get_live_browser_registry().get(str(self._resolve_user_data_dir()))
        if session is None or int(getattr(session, "debug_port", 0) or 0) <= 0:
            raise self._build_reuse_open_browser_unavailable_error(
                message=(
                    "No reusable OfferToday browser session is available for this profile. "
                    "Open the manual browser again or choose Fresh Profile."
                )
            )

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{session.debug_port}"
            )
        except Exception as exc:
            raise self._build_reuse_open_browser_unavailable_error(
                message=(
                    "The reusable OfferToday browser session is unavailable. "
                    "Reopen the manual browser or choose Fresh Profile."
                )
            ) from exc

        self._context = self._browser.contexts[0] if self._browser.contexts else None
        if self._context is None:
            raise self._build_reuse_open_browser_unavailable_error(
                message=(
                    "The reusable OfferToday browser session is unavailable. "
                    "Reopen the manual browser or choose Fresh Profile."
                )
            )
        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._owns_context = False
        self._owns_browser = False

    async def _warmup_page(self) -> None:
        if self._page is None:
            raise RuntimeError("OfferToday browser runtime was not initialized")
        await self._page.goto(
            f"{OFFERTODAY_BASE_URL}/hk/search",
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )

    async def _fetch_json(
        self,
        url: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self._page is None:
            raise RuntimeError("OfferToday browser runtime has not been started")

        fetch_options: dict[str, Any] = {
            "method": method,
            "headers": dict(OFFERTODAY_COMMON_HEADERS),
        }
        if payload is not None:
            fetch_options["body"] = json.dumps(payload, ensure_ascii=True)
        script = (
            "async ({ url, options }) => {"
            "  const response = await fetch(url, options);"
            "  return await response.json();"
            "}"
        )
        result = await self._page.evaluate(script, {"url": url, "options": fetch_options})
        return result if isinstance(result, dict) else None

    def _build_reuse_open_browser_unavailable_error(self, *, message: str) -> ManualActionRequiredError:
        return ManualActionRequiredError(
            source_site="offertoday",
            stage="browser_session",
            blocked_url=f"{OFFERTODAY_BASE_URL}/hk/search",
            referer=OFFERTODAY_BASE_URL,
            message=message,
            instructions=[
                "Reopen the OfferToday manual browser session for this profile.",
                "Or switch the resume strategy to Fresh Profile.",
            ],
        )

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / "offertoday" / self.browser_channel
        return Path(".playwright") / "offertoday" / self.browser_channel
