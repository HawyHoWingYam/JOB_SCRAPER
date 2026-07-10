from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Mapping, Protocol

from app.scraper.manual_action import RESUME_STRATEGY_FRESH_PROFILE
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailFetchResult,
    OfferTodayDetailIdentity,
    OfferTodayIdentityError,
    validate_offertoday_detail_identity,
)
from app.sources.offertoday.parsers import (
    OfferTodayPayloadParseError,
    parse_offertoday_detail_response,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
    classify_offertoday_response,
)


class DetailJsonFetcher(Protocol):
    async def __call__(
        self,
        *,
        job_id: str,
        encrypted_job_id: str,
    ) -> dict[str, Any] | None: ...


_WAF_CHALLENGE_PATH = "/web/passport/cm/verify"


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
        self.resume_strategy = (
            self.request_payload.get("resume_strategy") or RESUME_STRATEGY_FRESH_PROFILE
        )
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
            runtime = OfferTodayBrowserRuntime(
                headed=self.headed,
                auth_state_path=self.auth_state_path,
                resume_strategy=self.resume_strategy,
            )
            self._runtime = runtime
            try:
                await runtime.__aenter__()
                self._page = runtime._page
                await runtime.require_healthy_session()
            except BaseException as exc:
                try:
                    await runtime.__aexit__(type(exc), exc, exc.__traceback__)
                except BaseException as cleanup_exc:
                    exc.add_note(
                        "OfferToday browser runtime cleanup also failed: "
                        f"{cleanup_exc!r}"
                    )
                finally:
                    self._runtime = None
                    self._page = None
                raise
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
    ) -> OfferTodayDetailFetchResult:
        identity = self._build_request_identity(
            job_id=job_id,
            encrypted_job_id=encrypted_job_id,
        )
        classification = await self._fetch_and_classify(identity)

        if (
            classification.kind is OfferTodayResponseKind.IP_BLOCKED
            and self.headed
            and self._page is not None
        ):
            cleared = await self._await_manual_verification(identity.encrypted_job_id)
            if cleared:
                classification = await self._fetch_and_classify(identity)

        return self._build_fetch_result(identity, classification)

    @staticmethod
    def _build_request_identity(
        *,
        job_id: Any,
        encrypted_job_id: Any,
    ) -> OfferTodayDetailIdentity:
        if not isinstance(job_id, str) or not job_id.strip():
            raise OfferTodayIdentityError(
                f"Missing nonblank string jobId; got {job_id!r}"
            )
        if not isinstance(encrypted_job_id, str) or not encrypted_job_id.strip():
            raise OfferTodayIdentityError(
                f"Missing nonblank string encryptJobId; got {encrypted_job_id!r}"
            )
        return OfferTodayDetailIdentity(
            job_id=job_id.strip(),
            encrypted_job_id=encrypted_job_id.strip(),
        )

    async def _fetch_and_classify(
        self,
        identity: OfferTodayDetailIdentity,
    ) -> OfferTodayResponseClassification:
        try:
            payload = await self._fetch_detail_payload(identity)
        except Exception as exc:
            raw_payload = getattr(exc, "payload", None)
            payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else None
            response_url = getattr(exc, "response_url", None)
            current_url = (
                response_url
                if isinstance(response_url, str) and response_url.strip()
                else self._current_page_url()
            )
            http_status = getattr(exc, "http_status", None)
            return classify_offertoday_response(
                payload,
                operation="detail",
                current_url=current_url,
                expected_job_id=identity.job_id,
                transport_error=exc,
                http_status=http_status if isinstance(http_status, int) else None,
            )

        return classify_offertoday_response(
            payload,
            operation="detail",
            current_url=self._current_page_url(),
            expected_job_id=identity.job_id,
        )

    def _build_fetch_result(
        self,
        identity: OfferTodayDetailIdentity,
        classification: OfferTodayResponseClassification,
    ) -> OfferTodayDetailFetchResult:
        raw_response = (
            deepcopy(classification.raw_payload)
            if classification.raw_payload is not None
            else None
        )
        if classification.kind is not OfferTodayResponseKind.SUCCESS:
            return OfferTodayDetailFetchResult(
                identity=identity,
                classification=classification,
                raw_response=raw_response,
                parsed_detail=None,
                canonical_detail=None,
            )

        try:
            validate_offertoday_detail_identity(
                identity,
                classification.data or {},
            )
        except OfferTodayIdentityError as exc:
            return OfferTodayDetailFetchResult(
                identity=identity,
                classification=replace(
                    classification,
                    kind=OfferTodayResponseKind.ID_MISMATCH,
                    message=str(exc),
                    retryable=False,
                    stop_batch=True,
                ),
                raw_response=raw_response,
                parsed_detail=None,
                canonical_detail=None,
            )

        try:
            parsed_detail = parse_offertoday_detail_response(raw_response or {})
        except OfferTodayPayloadParseError as exc:
            return OfferTodayDetailFetchResult(
                identity=identity,
                classification=replace(
                    classification,
                    kind=OfferTodayResponseKind.INVALID_PAYLOAD,
                    message=str(exc),
                    retryable=False,
                    stop_batch=False,
                ),
                raw_response=raw_response,
                parsed_detail=None,
                canonical_detail=None,
            )
        validate_offertoday_detail_identity(identity, parsed_detail)
        canonical_detail = {
            **parsed_detail,
            "job_id": identity.job_id,
            "encrypted_job_id": identity.encrypted_job_id,
        }
        return OfferTodayDetailFetchResult(
            identity=identity,
            classification=classification,
            raw_response=raw_response,
            parsed_detail=parsed_detail,
            canonical_detail=canonical_detail,
        )

    async def _fetch_detail_payload(
        self,
        identity: OfferTodayDetailIdentity,
    ) -> dict[str, Any] | None:
        if self.detail_json_fetcher is not None:
            return await self.detail_json_fetcher(
                job_id=identity.job_id,
                encrypted_job_id=identity.encrypted_job_id,
            )
        if self._runtime is None:
            raise RuntimeError(
                "OfferTodayBrowserDetailScraper runtime has not been started"
            )
        return await self._runtime.fetch_detail_json(
            job_id=identity.job_id,
            encrypted_job_id=identity.encrypted_job_id,
        )

    def _current_page_url(self) -> str | None:
        current_url = getattr(self._page, "url", None)
        return current_url if isinstance(current_url, str) else None

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

    async def _await_manual_verification(self, encrypted_job_id: str) -> bool:
        if self._page is None:
            return False

        job_url = f"https://www.offertoday.com/hk/job/{encrypted_job_id}"
        try:
            await self._page.goto(
                job_url, wait_until="domcontentloaded", timeout=30_000
            )
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
