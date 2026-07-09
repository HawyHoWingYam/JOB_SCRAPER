from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.scraper.manual_action import RESUME_STRATEGY_FRESH_PROFILE
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime


DetailJsonFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]

_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"


class OfferTodayIPBlockedError(RuntimeError):
    def __init__(self, *, job_id: str, code: int) -> None:
        super().__init__(f"OfferToday detail fetch blocked for job_id={job_id} code={code}")
        self.job_id = job_id
        self.code = code


class OfferTodayDetailUnavailableError(RuntimeError):
    def __init__(self, *, job_id: str, code: int, message: str | None = None) -> None:
        resolved_message = str(message or "").strip() or "OfferToday detail fetch failed"
        super().__init__(
            f"OfferToday detail unavailable for job_id={job_id} code={code}: {resolved_message}"
        )
        self.job_id = job_id
        self.code = code
        self.message = resolved_message


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
        self._runtime: OfferTodayBrowserRuntime | None = None
        self._page = None

    @staticmethod
    def is_waf_challenge_url(url: str | None) -> bool:
        return _WAF_CHALLENGE_PATH in str(url or "")

    async def __aenter__(self):
        if self.detail_json_fetcher is None:
            self._runtime = OfferTodayBrowserRuntime(
                headed=self.headed,
                auth_state_path=self.auth_state_path,
                resume_strategy=self.resume_strategy,
            )
            await self._runtime.__aenter__()
            self._page = self._runtime._page
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._runtime is not None:
            runtime = self._runtime
            self._runtime = None
            await runtime.__aexit__(exc_type, exc, tb)
        self._page = None
        return None

    async def fetch_job_detail(
        self,
        job_id: str,
        *,
        encrypted_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        payload = await self._fetch_detail_payload(job_id, encrypted_job_id=encrypted_job_id)
        if not isinstance(payload, dict):
            return None
        if payload.get("code") == -1000035:
            if self.headed and self._page is not None:
                cleared = await self._await_manual_verification(job_id)
                if cleared:
                    payload = await self._fetch_detail_payload(
                        job_id,
                        encrypted_job_id=encrypted_job_id,
                    )
                    if not isinstance(payload, dict):
                        return None
                else:
                    raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
            else:
                raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
        if payload.get("code") == -1000035:
            raise OfferTodayIPBlockedError(job_id=job_id, code=-1000035)
        if payload.get("code") != 0:
            raise OfferTodayDetailUnavailableError(
                job_id=job_id,
                code=int(payload.get("code") or 0),
                message=payload.get("msg"),
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        if not str(data.get("jobId") or "").strip():
            return None
        return dict(data)

    async def _fetch_detail_payload(
        self,
        job_id: str,
        *,
        encrypted_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self.detail_json_fetcher is not None:
            return await self.detail_json_fetcher(job_id)
        if self._runtime is None:
            raise RuntimeError("OfferTodayBrowserDetailScraper runtime has not been started")
        return await self._runtime.fetch_detail_json(
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
        )

    async def _warmup_page(self) -> None:
        if self._page is None:
            return
        await self._page.goto(
            "https://www.offertoday.com/hk/search",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        if self.headed and self.is_waf_challenge_url(getattr(self._page, "url", None)):
            await self._page.wait_for_url(
                lambda current_url: not self.is_waf_challenge_url(current_url),
                timeout=self.manual_verification_timeout_seconds * 1000,
            )

    async def _await_manual_verification(self, job_id: str) -> bool:
        if self._page is None:
            return False

        job_url = f"https://www.offertoday.com/hk/job/{job_id}"
        try:
            await self._page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            return False

        if not self.is_waf_challenge_url(getattr(self._page, "url", None)):
            return True

        try:
            await self._page.wait_for_url(
                lambda current_url: not self.is_waf_challenge_url(current_url),
                timeout=self.manual_verification_timeout_seconds * 1000,
            )
        except Exception:
            return False

        await self._warmup_page()
        return True
