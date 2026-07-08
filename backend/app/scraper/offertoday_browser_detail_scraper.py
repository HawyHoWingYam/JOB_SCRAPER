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

    @staticmethod
    def is_waf_challenge_url(url: str | None) -> bool:
        return _WAF_CHALLENGE_PATH in str(url or "")

    async def __aenter__(self):
        if self.detail_json_fetcher is None:
            self._runtime = OfferTodayBrowserRuntime(resume_strategy=self.resume_strategy)
            await self._runtime.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._runtime is not None:
            runtime = self._runtime
            self._runtime = None
            await runtime.__aexit__(exc_type, exc, tb)
        return None

    async def fetch_job_detail(self, job_id: str) -> dict[str, Any] | None:
        payload = await self._fetch_detail_payload(job_id)
        if not isinstance(payload, dict):
            return None
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
        if self._runtime is None:
            raise RuntimeError("OfferTodayBrowserDetailScraper runtime has not been started")
        return await self._runtime.fetch_detail_json(job_id=job_id)
