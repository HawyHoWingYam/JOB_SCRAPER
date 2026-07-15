from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.browser_launch import launch_persistent_context_with_fallback_async
from app.scraper.manual_action import (
    ManualActionRequiredError,
    RESUME_STRATEGY_FRESH_PROFILE,
    RESUME_STRATEGY_REUSE_OPEN_BROWSER,
    build_session_recovery_manual_action,
    resolve_manual_action_cdp_connect_host,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_BASE_URL,
    OFFERTODAY_COMMON_HEADERS,
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayIdentityError,
    resolve_offertoday_detail_identity,
    resolve_offertoday_listing_identity,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayBrowserContextLostError,
    OfferTodayListingTransportResult,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
)

logger = logging.getLogger(__name__)


_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"
_HEADED_DISPLAY_UNAVAILABLE_MARKERS = (
    "Looks like you launched a headed browser without having a XServer running.",
    "Missing X server or $DISPLAY",
    "use 'xvfb-run",
)
_BROWSER_CONTEXT_LOST_MARKERS = (
    "target page, context or browser has been closed",
    "page has been closed",
    "browser has been closed",
    "target closed",
)
_BROWSER_FETCH_REJECTION_MARKERS = (
    "typeerror: failed to fetch",
    "networkerror when attempting to fetch resource",
)
_FAILED_FETCH_URL_SETTLE_DELAYS_SECONDS = (0.0, 0.05, 0.1)
_OFFERTODAY_DETAIL_URL_TEMPLATE = (
    f"{OFFERTODAY_BASE_URL}/wapi/geek/recommend/jobDetail?id=%s&encryptJobId=%s"
)


@dataclass(slots=True)
class OfferTodaySessionCheckResult:
    current_url: str
    is_waf_challenge: bool
    listing_probe_payload: dict[str, Any] | None
    listing_result_count: int
    classification: OfferTodayResponseKind
    api_code: int | None
    message: str | None
    healthy: bool


@dataclass(frozen=True, slots=True)
class _OfferTodayHttpJsonResponse:
    payload: dict[str, Any] | None
    http_status: int
    response_url: str


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
        self._context_id: str | None = None

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
        self._context_id = uuid4().hex
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
        self._context_id = None

    @property
    def browser_context_hash(self) -> str | None:
        if self._context_id is None:
            return None
        return hashlib.sha256(self._context_id.encode()).hexdigest()

    async def fetch_listing_json(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> dict[str, Any] | None:
        resolved_listing_url = self._resolve_listing_url(listing_url)
        return await self._fetch_json(
            resolved_listing_url,
            method="POST",
            payload=payload,
        )

    async def fetch_listing_page(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> OfferTodayListingTransportResult:
        """Return typed listing transport evidence without owning cursor state."""

        try:
            response = await self._fetch_json_response(
                self._resolve_listing_url(listing_url),
                method="POST",
                payload=payload,
            )
        except Exception as exc:
            message = str(exc or "").lower()
            if any(marker in message for marker in _BROWSER_CONTEXT_LOST_MARKERS):
                raise OfferTodayBrowserContextLostError(
                    "OfferToday browser context was lost during listing transport"
                ) from exc
            raise
        return OfferTodayListingTransportResult(
            payload=response.payload,
            browser_context_hash=self.browser_context_hash,
            http_status=response.http_status,
            response_url=response.response_url,
        )

    @staticmethod
    def _resolve_listing_url(listing_url: str | None) -> str:
        resolved_listing_url = (
            OFFERTODAY_LISTING_SEARCH_URL if listing_url is None else listing_url
        )
        if not isinstance(resolved_listing_url, str) or resolved_listing_url not in (
            OFFERTODAY_LISTING_SEARCH_URL,
            OFFERTODAY_LISTING_BROWSE_URL,
        ):
            raise ValueError(f"Unsupported OfferToday listing URL: {listing_url!r}")
        return resolved_listing_url

    async def fetch_detail_json(
        self,
        *,
        job_id: str,
        encrypted_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        identity = resolve_offertoday_detail_identity(
            source_job_id=job_id,
            listing_payload={
                "jobId": job_id,
                "encryptJobId": encrypted_job_id,
                "encrypted_job_id_source": "encryptJobId",
            },
        )
        return await self._fetch_json(
            _OFFERTODAY_DETAIL_URL_TEMPLATE
            % (identity.job_id, identity.encrypted_job_id),
            method="GET",
        )

    async def check_session(
        self,
        *,
        listing_payload: dict[str, Any] | None = None,
    ) -> OfferTodaySessionCheckResult:
        current_url = str(getattr(self._page, "url", "") or "")
        probe_payload: dict[str, Any] | None = None
        transport_error: BaseException | None = None
        http_status: int | None = None
        try:
            probe_payload = await self.fetch_listing_json(
                listing_payload or {"keyword": "", "page": 1, "pageSize": 1}
            )
        except (OfferTodayTransportError, TimeoutError, ConnectionError) as exc:
            transport_error = exc
            if isinstance(exc, OfferTodayTransportError):
                probe_payload = exc.payload
                http_status = exc.http_status
                current_url = str(exc.response_url or current_url)

        classification = classify_offertoday_response(
            probe_payload,
            operation="listing",
            current_url=current_url,
            transport_error=transport_error,
            http_status=http_status,
        )
        healthy = classification.kind is OfferTodayResponseKind.SUCCESS
        result_list = (
            (classification.data or {}).get("resultList") or [] if healthy else []
        )
        listing_result_count = len(result_list) if isinstance(result_list, list) else 0
        return OfferTodaySessionCheckResult(
            current_url=current_url,
            is_waf_challenge=(
                classification.kind is OfferTodayResponseKind.WAF_CHALLENGE
            ),
            listing_probe_payload=probe_payload,
            listing_result_count=listing_result_count,
            classification=classification.kind,
            api_code=classification.code,
            message=classification.message,
            healthy=healthy,
        )

    async def require_healthy_session(
        self,
        *,
        listing_payload: dict[str, Any] | None = None,
    ) -> OfferTodaySessionCheckResult:
        result = await self.check_session(listing_payload=listing_payload)
        if result.healthy:
            return result

        if result.classification in {
            OfferTodayResponseKind.AUTH_EXPIRED,
            OfferTodayResponseKind.WAF_CHALLENGE,
            OfferTodayResponseKind.IP_BLOCKED,
        }:
            raise build_session_recovery_manual_action(
                source_site="offertoday",
                stage="browser_session",
                blocked_url=(
                    result.current_url or f"{OFFERTODAY_BASE_URL}/hk/search"
                ),
                referer=OFFERTODAY_BASE_URL,
                classification=result.classification.value,
                code=result.api_code,
                evidence={
                    "final_url": result.current_url,
                    "api_code": result.api_code,
                    "reason": "session_preflight",
                },
                resume_context={
                    "classification": result.classification.value,
                    "api_code": result.api_code,
                    "message": result.message,
                },
            )

        raise RuntimeError(
            "OfferToday browser session preflight failed: "
            f"classification={result.classification.value}, "
            f"api_code={result.api_code}, message={result.message}"
        )

    async def run_smoke_test(
        self,
        *,
        listing_payload: dict[str, Any] | None = None,
        detail_limit: int = 1,
    ) -> dict[str, Any]:
        session_check = await self.check_session(listing_payload=listing_payload)
        smoke_result: dict[str, Any] = {
            "listing_ok": session_check.healthy,
            "listing_count": session_check.listing_result_count,
            "detail_results": [],
            "current_url": session_check.current_url,
            "is_waf_challenge": session_check.is_waf_challenge,
            "classification": session_check.classification.value,
            "api_code": session_check.api_code,
        }
        if not session_check.healthy:
            return smoke_result

        result_list = (
            (
                ((session_check.listing_probe_payload or {}).get("data") or {}).get(
                    "resultList"
                )
                or []
            )
            if isinstance(session_check.listing_probe_payload, dict)
            else []
        )
        detail_results: list[dict[str, Any]] = []
        resolved_detail_limit = max(int(detail_limit or 0), 0)
        for row in result_list:
            if len(detail_results) >= resolved_detail_limit:
                break
            if not isinstance(row, dict):
                continue
            try:
                identity = resolve_offertoday_listing_identity(row)
            except OfferTodayIdentityError:
                continue
            detail_payload = await self.fetch_detail_json(
                job_id=identity.job_id,
                encrypted_job_id=identity.encrypted_job_id,
            )
            detail_results.append(
                {
                    "job_id": identity.job_id,
                    "code": (
                        None
                        if not isinstance(detail_payload, dict)
                        else detail_payload.get("code")
                    ),
                }
            )
        smoke_result["detail_results"] = detail_results
        return smoke_result

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
        try:
            launch_result = await launch_persistent_context_with_fallback_async(
                self._playwright.chromium,
                user_data_dir=str(self._resolve_user_data_dir()),
                browser_channel=self.browser_channel,
                executable_path=self.executable_path,
                headless=False,
                extra_launch_kwargs={
                    key: value for key, value in launch_kwargs.items() if key != "headless"
                },
            )
        except Exception as exc:
            self._raise_if_headed_display_unavailable(exc)
            raise
        if launch_result.attempted_fallback:
            logger.warning(
                "offertoday_browser_channel_fallback requested=%s resolved=%s user_data_dir=%s",
                launch_result.requested_channel,
                launch_result.resolved_channel,
                str(self._resolve_user_data_dir()),
            )
        self._context = launch_result.context
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

        cdp_host = settings.manual_action_cdp_host or settings.manual_action_helper_host
        cdp_connect_host = resolve_manual_action_cdp_connect_host(cdp_host)
        logger.info(
            "manual_action_attach_attempt",
            extra={
                "strategy": self.resume_strategy,
                "source_site": "offertoday",
                "cdp_host": cdp_host,
                "cdp_connect_host": cdp_connect_host,
                "debug_port": session.debug_port,
                "browser_profile_path": str(self._resolve_user_data_dir()),
            },
        )
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                f"http://{cdp_connect_host}:{session.debug_port}"
            )
        except Exception as exc:
            logger.info(
                "manual_action_attach_failure",
                extra={
                    "strategy": self.resume_strategy,
                    "source_site": "offertoday",
                    "cdp_host": cdp_host,
                    "cdp_connect_host": cdp_connect_host,
                    "debug_port": session.debug_port,
                    "error": str(exc),
                },
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message=(
                    "The reusable OfferToday browser session is unavailable. "
                    "Reopen the manual browser or choose Fresh Profile."
                )
            ) from exc

        self._context = self._browser.contexts[0] if self._browser.contexts else None
        if self._context is None:
            logger.info(
                "manual_action_attach_failure",
                extra={
                    "strategy": self.resume_strategy,
                    "source_site": "offertoday",
                    "cdp_host": cdp_host,
                    "cdp_connect_host": cdp_connect_host,
                    "debug_port": session.debug_port,
                    "error": "Attached browser exposes no reusable context",
                },
            )
            raise self._build_reuse_open_browser_unavailable_error(
                message=(
                    "The reusable OfferToday browser session is unavailable. "
                    "Reopen the manual browser or choose Fresh Profile."
                )
            )
        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        # Use a dedicated page for automation probes instead of hijacking the user's current tab.
        self._page = await self._context.new_page()
        self._owns_context = False
        self._owns_browser = False
        logger.info(
            "manual_action_attach_success",
            extra={
                "strategy": self.resume_strategy,
                "source_site": "offertoday",
                "cdp_host": cdp_host,
                "cdp_connect_host": cdp_connect_host,
                "debug_port": session.debug_port,
            },
        )

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
        response = await self._fetch_json_response(
            url,
            method=method,
            payload=payload,
        )
        return response.payload

    async def _fetch_json_response(
        self,
        url: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> _OfferTodayHttpJsonResponse:
        if self._page is None:
            raise RuntimeError("OfferToday browser runtime has not been started")

        headers = dict(OFFERTODAY_COMMON_HEADERS)
        csrf_token = await self._read_csrf_token()
        if csrf_token:
            headers["csrf-token"] = csrf_token
        fetch_options: dict[str, Any] = {
            "method": method,
            "headers": headers,
            "credentials": "include",
        }
        if payload is not None:
            fetch_options["body"] = json.dumps(payload, ensure_ascii=True)
        script = (
            "async ({ url, options }) => {"
            "  const response = await fetch(url, options);"
            "  return {"
            "    httpStatus: response.status,"
            "    responseUrl: response.url,"
            "    text: await response.text(),"
            "  };"
            "}"
        )
        try:
            result = await self._page.evaluate(
                script,
                {"url": url, "options": fetch_options},
            )
        except Exception as exc:
            normalized_message = str(exc or "").lower()
            if not any(
                marker in normalized_message
                for marker in _BROWSER_FETCH_REJECTION_MARKERS
            ):
                raise
            response_url = await self._capture_failed_fetch_url(url)
            raise OfferTodayTransportError(
                "OfferToday browser fetch was interrupted",
                http_status=None,
                response_url=response_url,
                payload=None,
                error_kind="network",
            ) from exc
        if not isinstance(result, dict):
            raise RuntimeError(
                "OfferToday browser fetch returned invalid response metadata"
            )

        http_status = result.get("httpStatus")
        response_url = result.get("responseUrl")
        response_text = result.get("text")
        if type(http_status) is not int:
            raise RuntimeError(
                "OfferToday browser fetch returned an invalid HTTP status"
            )
        if not isinstance(response_url, str) or not response_url.strip():
            raise RuntimeError(
                "OfferToday browser fetch returned an invalid response URL"
            )
        if not isinstance(response_text, str):
            raise RuntimeError(
                "OfferToday browser fetch returned an invalid response body"
            )

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise OfferTodayTransportError(
                "OfferToday returned a non-JSON response",
                http_status=http_status,
                response_url=response_url,
                payload=None,
                error_kind="invalid_json",
            ) from exc

        parsed_payload = parsed if isinstance(parsed, dict) else None
        if not 200 <= http_status < 300 or self.is_waf_challenge_url(response_url):
            raise OfferTodayTransportError(
                f"OfferToday browser fetch failed with HTTP {http_status}",
                http_status=http_status,
                response_url=response_url,
                payload=parsed_payload,
                error_kind="http",
            )
        return _OfferTodayHttpJsonResponse(
            payload=parsed_payload,
            http_status=http_status,
            response_url=response_url,
        )

    async def _capture_failed_fetch_url(self, fallback_url: str) -> str:
        """Allow a navigation-aborted fetch to expose its redirect destination."""

        page = self._page
        current_url = str(getattr(page, "url", "") or fallback_url)
        if self.is_waf_challenge_url(current_url):
            return current_url

        for delay_seconds in _FAILED_FETCH_URL_SETTLE_DELAYS_SECONDS:
            await asyncio.sleep(delay_seconds)
            candidate_url = str(getattr(page, "url", "") or current_url)
            if candidate_url:
                current_url = candidate_url
            if self.is_waf_challenge_url(current_url):
                break
        return current_url

    async def _read_csrf_token(self) -> str | None:
        if self._page is None:
            raise RuntimeError("OfferToday browser runtime has not been started")

        script = (
            "() => {"
            "  const match = document.cookie.match(/(?:^|;\\s*)Csrf-Token=([^;]+)/);"
            "  return match ? decodeURIComponent(match[1]) : null;"
            "}"
        )
        token = await self._page.evaluate(script)
        resolved = str(token or "").strip()
        return resolved or None

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

    def _raise_if_headed_display_unavailable(self, exc: Exception) -> None:
        message = str(exc or "")
        if not any(marker in message for marker in _HEADED_DISPLAY_UNAVAILABLE_MARKERS):
            return

        logger.warning(
            "offertoday_headed_display_unavailable user_data_dir=%s error=%s",
            self._resolve_user_data_dir(),
            message.splitlines()[0] if message else type(exc).__name__,
        )
        raise ManualActionRequiredError(
            source_site="offertoday",
            stage="headed_display_unavailable",
            blocked_url=f"{OFFERTODAY_BASE_URL}/hk/search",
            message=(
                "OfferToday headed browser could not start because this runtime has no X server/$DISPLAY. "
                "Run the crawl in a desktop session with display support, or retry in headless mode."
            ),
            action_type="environment_setup",
            instructions=[
                "Run the backend in a desktop session with display support before retrying headed mode.",
                "Or retry the crawl in headless mode if manual verification is not required.",
            ],
        ) from exc

    def _resolve_user_data_dir(self) -> Path:
        if self.user_data_dir:
            return Path(self.user_data_dir)
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "job_scraper" / "playwright" / "offertoday" / self.browser_channel
        return Path(".playwright") / "offertoday" / self.browser_channel
