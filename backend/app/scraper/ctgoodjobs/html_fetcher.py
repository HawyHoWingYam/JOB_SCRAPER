from __future__ import annotations

import logging

import httpx

from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL
from app.utils.anti_detection import ExponentialBackoff, get_random_user_agent

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS_CODES = {502, 503, 504}
_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
_INTERSTITIAL_MARKERS = (
    "just a moment",
    "cf-challenge",
    "challenges.cloudflare.com",
    "verify you are human",
    "let's confirm you are human",
    "lets confirm you are human",
    "complete the security check before continuing",
)


class CTGoodJobsFetchError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        url: str,
        attempts: int,
        status_code: int | None = None,
        exception_type: str | None = None,
    ) -> None:
        details = (
            f"status_code={status_code}"
            if status_code is not None
            else f"exception_type={exception_type or 'unknown'}"
        )
        super().__init__(
            f"CTGoodJobs {stage} fetch failed after {attempts} attempts ({details}) url={url}"
        )
        self.stage = stage
        self.url = url
        self.attempts = attempts
        self.status_code = status_code
        self.exception_type = exception_type


def looks_like_interstitial_html(html: str) -> bool:
    lowered = (html or "").lower()
    return any(marker in lowered for marker in _INTERSTITIAL_MARKERS)


def build_document_headers(*, referer: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-HK,en;q=0.9,zh-HK;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Referer": referer or f"{CTGOODJOBS_BASE_URL}/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
    }


async def fetch_html_document(
    url: str,
    *,
    stage: str,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
    referer: str | None = None,
    max_attempts: int = 3,
) -> str:
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)

    backoff = ExponentialBackoff(base_delay=1.0, max_delay=8.0, max_retries=max_attempts, jitter=0.25)

    try:
        for attempt in range(max_attempts):
            try:
                response = await client.get(url, headers=build_document_headers(referer=referer))
                response.raise_for_status()
                if looks_like_interstitial_html(response.text):
                    if attempt == max_attempts - 1:
                        raise CTGoodJobsFetchError(
                            stage=stage,
                            url=url,
                            attempts=attempt + 1,
                            exception_type="InterstitialChallenge",
                        )
                    logger.warning(
                        "CTGoodJobs %s fetch hit human-verification interstitial: url=%s attempt=%s/%s",
                        stage,
                        url,
                        attempt + 1,
                        max_attempts,
                    )
                    await backoff.wait(attempt)
                    continue
                return response.text
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                is_retryable = status_code in _TRANSIENT_STATUS_CODES
                if (not is_retryable) or attempt == max_attempts - 1:
                    raise CTGoodJobsFetchError(
                        stage=stage,
                        url=url,
                        attempts=attempt + 1,
                        status_code=status_code,
                        exception_type=type(exc).__name__,
                    ) from exc
                logger.warning(
                    "Transient CTGoodJobs %s fetch failure: url=%s status_code=%s attempt=%s/%s",
                    stage,
                    url,
                    status_code,
                    attempt + 1,
                    max_attempts,
                )
            except _TRANSIENT_EXCEPTIONS as exc:
                if attempt == max_attempts - 1:
                    raise CTGoodJobsFetchError(
                        stage=stage,
                        url=url,
                        attempts=attempt + 1,
                        exception_type=type(exc).__name__,
                    ) from exc
                logger.warning(
                    "Transient CTGoodJobs %s fetch exception: url=%s exception_type=%s attempt=%s/%s",
                    stage,
                    url,
                    type(exc).__name__,
                    attempt + 1,
                    max_attempts,
                )

            await backoff.wait(attempt)
    finally:
        if owned:
            await client.aclose()

    raise AssertionError("unreachable")
