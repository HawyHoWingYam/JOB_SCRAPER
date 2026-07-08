from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.sources.offertoday.constants import OFFERTODAY_BASE_URL


DetailJsonFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]

OFFERTODAY_DETAIL_URL_TPL = (
    f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"
)
OFFERTODAY_JOB_URL_TPL = f"{OFFERTODAY_BASE_URL}/hk/job/%s"
_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"


class OfferTodayIPBlockedError(RuntimeError):
    def __init__(self, *, job_id: str, code: int) -> None:
        super().__init__(f"OfferToday detail fetch blocked for job_id={job_id} code={code}")
        self.job_id = job_id
        self.code = code


class OfferTodayBrowserDetailScraper:
    def __init__(
        self,
        *,
        detail_json_fetcher: DetailJsonFetcher | None = None,
        auth_state_path: str | None = None,
        headed: bool = False,
        manual_verification_timeout_seconds: int = 180,
    ) -> None:
        self.detail_json_fetcher = detail_json_fetcher
        self.auth_state_path = auth_state_path
        self.headed = headed
        self.manual_verification_timeout_seconds = manual_verification_timeout_seconds
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @staticmethod
    def is_waf_challenge_url(url: str | None) -> bool:
        return _WAF_CHALLENGE_PATH in str(url or "")

    async def __aenter__(self):
        if self.detail_json_fetcher is None:
            await self._start_runtime()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stop_runtime()
        return None

    async def fetch_job_detail(self, job_id: str) -> dict[str, Any] | None:
        payload = await self._fetch_detail_payload(job_id)
        if not isinstance(payload, dict):
            return None
        if payload.get("code") == -1000035:
            if self.headed and self._page is not None:
                cleared = await self._await_manual_verification(job_id)
                if cleared:
                    payload = await self._fetch_detail_payload(job_id)
                    if not isinstance(payload, dict):
                        return None
                else:
                    raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
            else:
                raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
        if payload.get("code") == -1000035:
            raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
        if payload.get("code") != 0:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        if not str(data.get("jobId") or "").strip():
            return None
        return dict(data)

    async def _fetch_detail_payload(self, job_id: str) -> dict[str, Any] | None:
        if self.detail_json_fetcher is not None:
            return await self.detail_json_fetcher(job_id)
        if self._page is None:
            raise RuntimeError("OfferTodayBrowserDetailScraper runtime has not been started")

        detail_url = OFFERTODAY_DETAIL_URL_TPL % (job_id, job_id)
        js = (
            f"()=>fetch('{detail_url}',{{headers:{{"
            f"'api-language':'zh_HK','x-requested-with':'XMLHttpRequest'}}}})"
            f".then(async r=>({{status:r.status, body: await r.text()}}))"
        )
        try:
            response = await asyncio.wait_for(self._page.evaluate(js), timeout=30)
        except Exception:
            return None

        if not isinstance(response, dict):
            return None

        body = str(response.get("body") or "").strip()
        if not body:
            return None

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return None

        return parsed if isinstance(parsed, dict) else None

    async def _start_runtime(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_args = [] if self.headed else ["--no-sandbox", "--disable-dev-shm-usage"]
        self._browser = await self._playwright.chromium.launch(
            headless=not self.headed,
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
        self._page = await self._context.new_page()
        await self._warmup_page()

    async def _warmup_page(self) -> None:
        if self._page is None:
            return
        await self._page.goto(
            f"{OFFERTODAY_BASE_URL}/hk/search",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        if self.headed and self.is_waf_challenge_url(self._page.url):
            await self._page.wait_for_url(
                lambda current_url: not self.is_waf_challenge_url(current_url),
                timeout=self.manual_verification_timeout_seconds * 1000,
            )
        await asyncio.sleep(2.0)

    async def _await_manual_verification(self, job_id: str) -> bool:
        if self._page is None:
            return False

        job_url = OFFERTODAY_JOB_URL_TPL % job_id
        try:
            await self._page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            return False

        if not self.is_waf_challenge_url(self._page.url):
            return True

        try:
            await self._page.wait_for_url(
                lambda current_url: not self.is_waf_challenge_url(current_url),
                timeout=self.manual_verification_timeout_seconds * 1000,
            )
        except Exception:
            return False

        await asyncio.sleep(1.5)
        await self._warmup_page()
        return True

    async def _stop_runtime(self) -> None:
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
