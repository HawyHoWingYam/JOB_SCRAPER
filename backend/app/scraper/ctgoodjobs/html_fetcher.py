from __future__ import annotations

import logging

import httpx

from app.scraper.access_block import classify_public_access_evidence
from app.scraper.ctgoodjobs.category_registry import CTGOODJOBS_BASE_URL
from app.scraper.log_events import build_scrape_log_event
from app.scraper.manual_action import build_session_recovery_manual_action
from app.scraper.proxy_rotation import (
    CTGoodJobsProxyRuntime,
    build_ctgoodjobs_proxy_runtime,
    get_active_ctgoodjobs_proxy_runtime,
)
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
        challenge_detected: bool = False,
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
        self.challenge_detected = bool(challenge_detected)


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
    proxy_runtime: CTGoodJobsProxyRuntime | None = None,
) -> str:
    active_proxy_runtime = (
        proxy_runtime
        or get_active_ctgoodjobs_proxy_runtime()
        or build_ctgoodjobs_proxy_runtime()
    )
    effective_timeout_s = (
        active_proxy_runtime.request_timeout_s
        if active_proxy_runtime.enabled
        else timeout_s
    )
    owned_client = client is None and not active_proxy_runtime.enabled
    if owned_client:
        client = httpx.AsyncClient(
            timeout=effective_timeout_s,
            follow_redirects=True,
            trust_env=False,
        )

    backoff = ExponentialBackoff(base_delay=1.0, max_delay=8.0, max_retries=max_attempts, jitter=0.25)

    try:
        for attempt in range(max_attempts):
            attempt_client = client
            attempt_proxy_lease = None
            owns_attempt_client = False
            try:
                logger.debug(
                    build_scrape_log_event(
                        "SCRAPE_FETCH_START",
                        source="ctgoodjobs",
                        stage=stage,
                        url=url,
                        attempt=attempt + 1,
                    )
                )
                if active_proxy_runtime.enabled:
                    attempt_proxy_lease = await active_proxy_runtime.acquire_lease()
                    attempt_client = httpx.AsyncClient(
                        timeout=effective_timeout_s,
                        follow_redirects=True,
                        trust_env=False,
                        **active_proxy_runtime.build_httpx_client_kwargs(attempt_proxy_lease),
                    )
                    owns_attempt_client = True
                request_headers = active_proxy_runtime.merge_request_headers(
                    build_document_headers(referer=referer)
                )
                response = await attempt_client.get(url, headers=request_headers)
                access_evidence = classify_public_access_evidence(
                    status_code=response.status_code,
                    final_url=str(response.url),
                    text=(
                        response.text
                        if len(response.text) <= 65536
                        else response.text[:4096]
                    ),
                    headers=response.headers,
                )
                if (
                    access_evidence is not None
                    and access_evidence.classification == "ip_blocked"
                ):
                    if active_proxy_runtime.enabled:
                        await active_proxy_runtime.report_challenge(
                            stage=stage,
                            lease=attempt_proxy_lease,
                        )
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_FETCH_MANUAL_ACTION",
                            source="ctgoodjobs",
                            stage=stage,
                            classification="ip_blocked",
                            status_code=access_evidence.status_code,
                            reason=access_evidence.reason,
                            attempt=attempt + 1,
                        )
                    )
                    raise build_session_recovery_manual_action(
                        source_site="ctgoodjobs",
                        stage=stage,
                        blocked_url=access_evidence.final_url or url,
                        referer=referer,
                        classification="ip_blocked",
                        evidence=access_evidence.to_payload(),
                    )
                response.raise_for_status()
                if (
                    access_evidence is not None
                    and access_evidence.classification == "waf_challenge"
                ) or looks_like_interstitial_html(response.text):
                    if active_proxy_runtime.enabled:
                        await active_proxy_runtime.report_challenge(
                            stage=stage,
                            lease=attempt_proxy_lease,
                        )
                    if attempt == max_attempts - 1:
                        challenge_evidence = (
                            access_evidence.to_payload()
                            if access_evidence is not None
                            else {
                                "final_url": str(response.url),
                                "status_code": response.status_code,
                                "reason": "interstitial_marker",
                            }
                        )
                        raise build_session_recovery_manual_action(
                            source_site="ctgoodjobs",
                            stage=stage,
                            blocked_url=str(response.url or url),
                            referer=referer,
                            classification="waf_challenge",
                            evidence=challenge_evidence,
                        )
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_FETCH_RETRY",
                            source="ctgoodjobs",
                            stage=stage,
                            classification="waf_challenge",
                            attempt=attempt + 1,
                            max_attempts=max_attempts,
                        )
                    )
                    await backoff.wait(attempt)
                    continue
                if active_proxy_runtime.enabled:
                    await active_proxy_runtime.report_success(
                        stage=stage,
                        lease=attempt_proxy_lease,
                    )
                logger.debug(
                    build_scrape_log_event(
                        "SCRAPE_FETCH_OK",
                        source="ctgoodjobs",
                        stage=stage,
                        url=url,
                        attempt=attempt + 1,
                    )
                )
                return response.text
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if active_proxy_runtime.enabled:
                    await active_proxy_runtime.report_http_failure(
                        stage=stage,
                        lease=attempt_proxy_lease,
                        status_code=status_code,
                    )
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
                if active_proxy_runtime.enabled:
                    await active_proxy_runtime.report_network_failure(
                        stage=stage,
                        lease=attempt_proxy_lease,
                    )
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
            finally:
                if owns_attempt_client and attempt_client is not None:
                    await attempt_client.aclose()

            await backoff.wait(attempt)
    finally:
        if owned_client and client is not None:
            await client.aclose()

    raise AssertionError("unreachable")
