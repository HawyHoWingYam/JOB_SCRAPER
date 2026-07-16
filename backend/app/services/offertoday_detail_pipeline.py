from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from app.scraper.log_events import build_scrape_log_event
from app.sources.contracts import (
    build_offertoday_canonical_job,
    build_offertoday_company_data,
    build_offertoday_job_data,
)

from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayIdentityError,
    build_offertoday_identity_authority_index,
    resolve_offertoday_detail_identity,
    validate_offertoday_detail_identity,
)
from app.sources.offertoday.parsers import (
    OfferTodayPayloadParseError,
    build_offertoday_job_url,
    parse_offertoday_detail_response,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
)
from app.services.crawl_cancellation_token import CrawlCancellationRequested

logger = logging.getLogger(__name__)


class DetailFetcher(Protocol):
    async def __call__(
        self,
        *,
        job_id: str,
        encrypted_job_id: str,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class OfferTodayDetailTarget:
    listing_id: Any
    duplicate_listing_ids: tuple[Any, ...]
    identity: OfferTodayDetailIdentity
    listing_payload: dict[str, Any]

    @property
    def listing_ids(self) -> tuple[Any, ...]:
        return (self.listing_id, *self.duplicate_listing_ids)

    @classmethod
    def from_runtime_target(
        cls,
        target: dict[str, Any],
    ) -> OfferTodayDetailTarget:
        listing_payload = deepcopy(dict(target.get("listing_payload") or {}))
        listing_identity = resolve_offertoday_detail_identity(
            source_job_id=target.get("source_job_id"),
            listing_payload=listing_payload,
        )
        supplied_identity = target.get("identity")
        if supplied_identity is None:
            identity = listing_identity
        elif not isinstance(supplied_identity, OfferTodayDetailIdentity):
            raise ValueError("OfferToday runtime target identity must be typed")
        else:
            authority_index = build_offertoday_identity_authority_index(
                (listing_identity, supplied_identity)
            )
            if authority_index.conflict_reason_by_job:
                raise ValueError("OfferToday runtime target identity is conflicting")
            identity = authority_index.authoritative_identity_by_job[
                listing_identity.job_id
            ]
            if identity != supplied_identity:
                raise ValueError(
                    "OfferToday runtime target identity does not match "
                    "authoritative identity"
                )
        return cls(
            listing_id=target["listing_id"],
            duplicate_listing_ids=tuple(target.get("duplicate_listing_ids") or ()),
            identity=identity,
            listing_payload=listing_payload,
        )


@dataclass(frozen=True, slots=True)
class OfferTodayDetailProcessResult:
    source_job_id: str
    outcome: OfferTodayResponseKind
    job_action: str | None = None
    company_action: str | None = None
    stop_batch: bool = False


class OfferTodayDetailPipeline:
    def __init__(
        self,
        *,
        session_factory,
        crawl_runtime,
        company_repository,
        job_repository,
        sleep=asyncio.sleep,
        clock=time.perf_counter,
        max_attempts: int = 3,
        retry_delays_seconds: tuple[float, ...] = (1.0, 2.0),
    ) -> None:
        self.session_factory = session_factory
        self.crawl_runtime = crawl_runtime
        self.company_repository = company_repository
        self.job_repository = job_repository
        self.sleep = sleep
        self.clock = clock
        self.max_attempts = max(1, min(int(max_attempts), 3))
        self.retry_delays_seconds = tuple(
            max(float(delay), 0.0) for delay in retry_delays_seconds
        )

    async def process_target(
        self,
        *,
        target: OfferTodayDetailTarget,
        detail_crawl_job_id,
        fetch_detail: DetailFetcher,
        crawl_mode: str | None = None,
    ) -> OfferTodayDetailProcessResult:
        prepared_payload: dict[str, Any] | None = None
        persisted_detail_payload: dict[str, Any] | None = None
        canonical_job = None
        classification: OfferTodayResponseClassification | None = None

        for attempt in range(1, self.max_attempts + 1):
            self._transition_running(
                listing_id=target.listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            started_at = float(self.clock())
            raw_response: dict[str, Any] | None = None
            transport_error: Exception | None = None
            try:
                fetched = await fetch_detail(
                    job_id=target.identity.job_id,
                    encrypted_job_id=target.identity.encrypted_job_id,
                )
                raw_response = dict(fetched) if isinstance(fetched, dict) else None
            except CrawlCancellationRequested:
                raise
            except (OfferTodayTransportError, TimeoutError, ConnectionError) as exc:
                transport_error = exc
            except Exception as exc:
                self._transition_outcome(
                    target=target,
                    detail_crawl_job_id=detail_crawl_job_id,
                    detail_status="failed",
                    error_message=f"unexpected_fetch_error:{type(exc).__name__}",
                )
                raise

            latency_seconds = max(float(self.clock()) - started_at, 0.0)
            transport_payload = (
                getattr(transport_error, "payload", None)
                if transport_error is not None
                else raw_response
            )
            classification = classify_offertoday_response(
                transport_payload,
                operation="detail",
                current_url=(
                    getattr(transport_error, "response_url", None)
                    if transport_error is not None
                    else None
                ),
                expected_job_id=target.identity.job_id,
                transport_error=transport_error,
                http_status=(
                    getattr(transport_error, "http_status", None)
                    if transport_error is not None
                    else None
                ),
            )

            if classification.kind is OfferTodayResponseKind.SUCCESS:
                try:
                    parsed_detail = parse_offertoday_detail_response(
                        classification.raw_payload or {}
                    )
                    validate_offertoday_detail_identity(
                        target.identity,
                        parsed_detail,
                    )
                    persisted_detail_payload = self._build_persisted_detail_payload(
                        target=target,
                        parsed_detail=parsed_detail,
                    )
                    prepared_payload = self._build_canonical_payload(
                        target=target,
                        persisted_detail=persisted_detail_payload,
                    )
                    canonical_job = build_offertoday_canonical_job(
                        prepared_payload,
                        identity=target.identity,
                    )
                    self._validate_required_canonical_fields(canonical_job)
                except OfferTodayIdentityError as exc:
                    classification = self._reclassify(
                        classification,
                        kind=OfferTodayResponseKind.ID_MISMATCH,
                        message=str(exc),
                        stop_batch=True,
                    )
                except (
                    OfferTodayPayloadParseError,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    classification = self._reclassify(
                        classification,
                        kind=OfferTodayResponseKind.INVALID_PAYLOAD,
                        message=str(exc),
                        stop_batch=False,
                    )

            will_retry = (
                classification.kind is OfferTodayResponseKind.TRANSIENT_TRANSPORT
                and attempt < self.max_attempts
            )
            try:
                self._record_attempt(
                    detail_crawl_job_id=detail_crawl_job_id,
                    target=target,
                    attempt=attempt,
                    classification=classification,
                    latency_seconds=latency_seconds,
                    will_retry=will_retry,
                    http_status=(
                        getattr(transport_error, "http_status", None)
                        if transport_error is not None
                        else None
                    ),
                )
                if will_retry:
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_RETRY",
                            source="offertoday",
                            crawl_job_id=detail_crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=crawl_mode,
                            source_job_id=target.identity.job_id,
                            attempt=attempt,
                            max_attempts=self.max_attempts,
                            elapsed_ms=max(
                                int(latency_seconds * 1000),
                                0,
                            ),
                            classification=classification.kind.value,
                            code=classification.code,
                        )
                    )
                elif classification.stop_batch:
                    logger.warning(
                        build_scrape_log_event(
                            "SCRAPE_DETAIL_MANUAL_ACTION",
                            source="offertoday",
                            crawl_job_id=detail_crawl_job_id,
                            crawl_phase="detail",
                            crawl_mode=crawl_mode,
                            source_job_id=target.identity.job_id,
                            attempt=attempt,
                            elapsed_ms=max(
                                int(latency_seconds * 1000),
                                0,
                            ),
                            classification=classification.kind.value,
                            code=classification.code,
                        )
                    )
            except Exception as exc:
                final_non_success = (
                    not will_retry
                    and classification.kind is not OfferTodayResponseKind.SUCCESS
                )
                if final_non_success:
                    detail_status = self._detail_status_for(classification.kind)
                    outcome = classification.kind
                    error_message = (
                        f"{self._classification_error(classification)};"
                        f"attempt_event_failure:{type(exc).__name__}"
                    )
                else:
                    detail_status = "failed"
                    outcome = OfferTodayResponseKind.PERSIST_FAILURE
                    error_message = f"attempt_event_failure:{type(exc).__name__}"
                self._transition_outcome(
                    target=target,
                    detail_crawl_job_id=detail_crawl_job_id,
                    detail_status=detail_status,
                    error_message=error_message,
                    detail_payload=classification.raw_payload,
                )
                return OfferTodayDetailProcessResult(
                    source_job_id=target.identity.job_id,
                    outcome=outcome,
                    stop_batch=classification.stop_batch,
                )
            if will_retry:
                delay_index = attempt - 1
                delay = (
                    self.retry_delays_seconds[delay_index]
                    if delay_index < len(self.retry_delays_seconds)
                    else 0.0
                )
                await self.sleep(delay)
                continue
            break

        if classification is None:
            raise RuntimeError("OfferToday detail pipeline made no fetch attempt")
        if classification.kind is not OfferTodayResponseKind.SUCCESS:
            detail_status = self._detail_status_for(classification.kind)
            self._transition_outcome(
                target=target,
                detail_crawl_job_id=detail_crawl_job_id,
                detail_status=detail_status,
                error_message=self._classification_error(classification),
                detail_payload=classification.raw_payload,
            )
            return OfferTodayDetailProcessResult(
                source_job_id=target.identity.job_id,
                outcome=classification.kind,
                stop_batch=classification.stop_batch,
            )

        if (
            prepared_payload is None
            or persisted_detail_payload is None
            or canonical_job is None
        ):
            raise RuntimeError("Successful OfferToday detail classification has no canonical payload")
        return self._persist_success(
            target=target,
            detail_crawl_job_id=detail_crawl_job_id,
            detail_payload=persisted_detail_payload,
            failure_detail_payload=classification.raw_payload,
            canonical_job=canonical_job,
        )

    def _transition_running(self, *, listing_id, detail_crawl_job_id) -> None:
        db = self.session_factory()
        try:
            self.crawl_runtime.transition_detail_running(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _transition_outcome(
        self,
        *,
        target: OfferTodayDetailTarget,
        detail_crawl_job_id,
        detail_status: str,
        error_message: str,
        detail_payload: dict[str, Any] | None = None,
    ) -> None:
        db = self.session_factory()
        try:
            self.crawl_runtime.transition_detail_outcome(
                db,
                listing_ids=target.listing_ids,
                detail_crawl_job_id=detail_crawl_job_id,
                status=detail_status,
                error_message=error_message,
                detail_payload=detail_payload,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _record_attempt(
        self,
        *,
        detail_crawl_job_id,
        target: OfferTodayDetailTarget,
        attempt: int,
        classification: OfferTodayResponseClassification,
        latency_seconds: float,
        will_retry: bool,
        http_status: int | None,
    ) -> None:
        self.crawl_runtime.write_progress_event(
            crawl_job_id=detail_crawl_job_id,
            event_type="crawl.detail_attempt",
            emitted_by="offertoday-detail-pipeline",
            payload={
                "detail_crawl_job_id": str(detail_crawl_job_id),
                "source_job_id": target.identity.job_id,
                "encrypted_job_id": target.identity.encrypted_job_id,
                "encrypted_job_id_source": (
                    target.identity.encrypted_job_id_source
                ),
                "attempt": int(attempt),
                "classification": classification.kind.value,
                "api_code": classification.code,
                "http_status": http_status,
                "latency_ms": max(int(float(latency_seconds) * 1000), 0),
                "will_retry": bool(will_retry),
                "stop_batch": bool(classification.stop_batch),
            },
        )

    @staticmethod
    def _build_persisted_detail_payload(
        *,
        target: OfferTodayDetailTarget,
        parsed_detail: dict[str, Any],
    ) -> dict[str, Any]:
        detail_raw = deepcopy(dict(parsed_detail.get("raw_data") or {}))
        return {
            **deepcopy(parsed_detail),
            "job_id": target.identity.job_id,
            "encrypted_job_id": target.identity.encrypted_job_id,
            "encrypted_job_id_source": target.identity.encrypted_job_id_source,
            "canonical_job_url": build_offertoday_job_url(
                target.identity.encrypted_job_id
            ),
            "raw_data": detail_raw,
        }

    @staticmethod
    def _build_canonical_payload(
        *,
        target: OfferTodayDetailTarget,
        persisted_detail: dict[str, Any],
    ) -> dict[str, Any]:
        listing_raw = deepcopy(dict(target.listing_payload.get("raw_data") or {}))
        detail_raw = deepcopy(dict(persisted_detail.get("raw_data") or {}))
        return {
            **deepcopy(target.listing_payload),
            **deepcopy(persisted_detail),
            "raw_data": {**listing_raw, **detail_raw},
        }

    @staticmethod
    def _validate_required_canonical_fields(canonical_job) -> None:
        required = {
            "title": canonical_job.title,
            "company": canonical_job.company_name,
            "description": canonical_job.description,
        }
        missing = [
            field_name
            for field_name, value in required.items()
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            raise ValueError(
                "OfferToday canonical detail is missing required fields: "
                + ", ".join(missing)
            )

    def _persist_success(
        self,
        *,
        target: OfferTodayDetailTarget,
        detail_crawl_job_id,
        detail_payload: dict[str, Any],
        failure_detail_payload: dict[str, Any] | None,
        canonical_job,
    ) -> OfferTodayDetailProcessResult:
        db = self.session_factory()
        try:
            company_data = build_offertoday_company_data(canonical_job)
            company, company_action = self.company_repository.upsert_company(
                db,
                company_data,
                auto_commit=False,
            )
            job_data = build_offertoday_job_data(canonical_job, company.id)
            raw_data = dict(job_data.get("raw_data") or {})
            raw_data["canonical_job_url"] = canonical_job.source_url
            job_data["raw_data"] = raw_data
            published_job, job_action = self.job_repository.upsert_source_job(
                db,
                job_data,
                skip_existing=False,
                auto_commit=False,
            )
            self.crawl_runtime.transition_detail_completed(
                db,
                listing_ids=target.listing_ids,
                detail_crawl_job_id=detail_crawl_job_id,
                detail_payload=detail_payload,
                published_job_id=published_job.id,
            )
            self.crawl_runtime.record_detail_persisted(
                db,
                detail_crawl_job_id=detail_crawl_job_id,
                source_job_id=target.identity.job_id,
                encrypted_job_id=target.identity.encrypted_job_id,
                encrypted_job_id_source=target.identity.encrypted_job_id_source,
                listing_ids=target.listing_ids,
                published_job_id=published_job.id,
                response_identity_hash=self._response_identity_hash(target.identity),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            self._transition_outcome(
                target=target,
                detail_crawl_job_id=detail_crawl_job_id,
                detail_status="failed",
                error_message=f"persist_failure:{type(exc).__name__}",
                detail_payload=failure_detail_payload,
            )
            return OfferTodayDetailProcessResult(
                source_job_id=target.identity.job_id,
                outcome=OfferTodayResponseKind.PERSIST_FAILURE,
                stop_batch=False,
            )
        finally:
            db.close()

        return OfferTodayDetailProcessResult(
            source_job_id=target.identity.job_id,
            outcome=OfferTodayResponseKind.SUCCESS,
            job_action=job_action,
            company_action=company_action,
            stop_batch=False,
        )

    @staticmethod
    def _response_identity_hash(identity: OfferTodayDetailIdentity) -> str:
        canonical_json = json.dumps(
            {
                "encrypted_job_id": identity.encrypted_job_id,
                "encrypted_job_id_source": identity.encrypted_job_id_source,
                "job_id": identity.job_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _reclassify(
        classification: OfferTodayResponseClassification,
        *,
        kind: OfferTodayResponseKind,
        message: str,
        stop_batch: bool,
    ) -> OfferTodayResponseClassification:
        return OfferTodayResponseClassification(
            kind=kind,
            code=classification.code,
            message=message,
            data=classification.data,
            raw_payload=classification.raw_payload,
            retryable=False,
            stop_batch=stop_batch,
        )

    @staticmethod
    def _detail_status_for(kind: OfferTodayResponseKind) -> str:
        if kind in {
            OfferTodayResponseKind.AUTH_EXPIRED,
            OfferTodayResponseKind.WAF_CHALLENGE,
            OfferTodayResponseKind.IP_BLOCKED,
        }:
            return "manual_action_required"
        if kind is OfferTodayResponseKind.TERMINAL_UNAVAILABLE:
            return "terminal_unavailable"
        if kind is OfferTodayResponseKind.ID_MISMATCH:
            return "identity_conflict"
        return "failed"

    @staticmethod
    def _classification_error(
        classification: OfferTodayResponseClassification,
    ) -> str:
        message = str(classification.message or "").strip()
        if message:
            return f"{classification.kind.value}:{message}"
        return classification.kind.value
