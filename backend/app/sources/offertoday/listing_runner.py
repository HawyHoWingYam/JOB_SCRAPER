from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
    build_offertoday_listing_payload,
)
from app.sources.offertoday.parsers import parse_offertoday_listing_response
from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
    classify_offertoday_response,
)


@dataclass(frozen=True, slots=True)
class OfferTodayListingCondition:
    search_family: str
    category_id: int | None
    keyword: str
    endpoint: Literal["search", "browse"]
    rcd_type: int | None = 7

    @property
    def condition_id(self) -> str:
        canonical_json = json.dumps(
            {
                "category_id": self.category_id,
                "endpoint": self.endpoint,
                "keyword": self.keyword,
                "rcd_type": self.rcd_type,
                "search_family": self.search_family,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_json.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ListingStopPolicy:
    max_pages_per_condition: int
    unique_job_cap: int | None = None
    require_empty_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.max_pages_per_condition < 1:
            raise ValueError("max_pages_per_condition must be >= 1")


@dataclass(frozen=True, slots=True)
class ListingRetryPolicy:
    max_attempts_per_page: int = 3
    retry_delays_seconds: tuple[float, ...] = (1.0, 2.0)
    page_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts_per_page < 1:
            raise ValueError("max_attempts_per_page must be >= 1")


@dataclass(frozen=True, slots=True)
class OfferTodayIdentityPair:
    job_id: str
    encrypted_job_id: str


@dataclass(frozen=True, slots=True)
class ListingIdentityIssue:
    job_id: str | None
    encrypted_job_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ListingRowEvidence:
    job_id: str | None
    encrypted_job_id: str | None
    title: str
    job_function_codes: tuple[str, ...]
    title_language: Literal["zh", "en", "mixed", "other"]
    api_language: str


@dataclass(frozen=True, slots=True)
class ListingIdentityConflict:
    job_ids: tuple[str, ...]
    encrypted_job_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ListingGap:
    condition_id: str
    page: int
    attempts: int
    last_kind: OfferTodayResponseKind


@dataclass(frozen=True, slots=True)
class ListingPageObservation:
    condition_id: str
    search_family: str
    category_id: int | None
    keyword: str
    endpoint: str
    rcd_type: int | None
    page: int
    attempt: int
    request_fingerprint: str
    classification: str
    api_code: int | None
    reported_total: int | None
    has_more: bool | None
    row_count: int
    missing_job_id_count: int
    missing_encrypted_job_id_count: int
    id_pairs: tuple[OfferTodayIdentityPair, ...]
    rows: tuple[ListingRowEvidence, ...]
    identity_issues: tuple[ListingIdentityIssue, ...]
    identity_conflicts: tuple[ListingIdentityConflict, ...]
    latency_ms: int
    session_mode: str
    retry_reason: str | None
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class ListingConditionOutcome:
    condition: OfferTodayListingCondition
    pages_observed: int
    stop_reason: str
    is_complete: bool


@dataclass(frozen=True, slots=True)
class ListingRunResult:
    ordered_job_ids: tuple[str, ...]
    accepted_job_ids: tuple[str, ...]
    id_pairs: tuple[OfferTodayIdentityPair, ...]
    observations: tuple[ListingPageObservation, ...]
    condition_outcomes: tuple[ListingConditionOutcome, ...]
    identity_conflicts: tuple[ListingIdentityConflict, ...]
    identity_issues: tuple[ListingIdentityIssue, ...]
    gaps: tuple[ListingGap, ...]
    stop_reason: str
    is_complete: bool


class OfferTodayListingTransport(Protocol):
    async def fetch_listing_json(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> dict[str, Any] | None: ...


class ListingObservationSink(Protocol):
    async def record_page_attempt(
        self,
        observation: ListingPageObservation,
    ) -> None: ...

    async def record_condition_outcome(
        self,
        outcome: ListingConditionOutcome,
    ) -> None: ...


class ListingStagingSink(Protocol):
    async def stage_page(
        self,
        *,
        condition: OfferTodayListingCondition,
        page: int,
        rows: list[dict[str, Any]],
    ) -> None: ...

    async def defer_identity_conflict(
        self,
        *,
        job_ids: tuple[str, ...],
        encrypted_job_ids: tuple[str, ...],
        reason: str,
    ) -> None: ...


def _classify_title_language(
    title: str,
) -> Literal["zh", "en", "mixed", "other"]:
    has_english = any("a" <= character.lower() <= "z" for character in title)
    has_chinese = any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in title
    )
    if has_english and has_chinese:
        return "mixed"
    if has_chinese:
        return "zh"
    if has_english:
        return "en"
    return "other"


def _request_fingerprint(listing_url: str, payload: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        {"payload": payload, "url": listing_url},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode()).hexdigest()


def _listing_url(condition: OfferTodayListingCondition) -> str:
    if condition.endpoint == "browse":
        return OFFERTODAY_LISTING_BROWSE_URL
    return OFFERTODAY_LISTING_SEARCH_URL


def _retry_delay(policy: ListingRetryPolicy, attempt: int) -> float:
    if not policy.retry_delays_seconds:
        return 0.0
    index = min(attempt - 1, len(policy.retry_delays_seconds) - 1)
    return policy.retry_delays_seconds[index]


def _normalized_optional_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _job_function_codes(job_functions: Any) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[str] = set()

    def add_code(value: Any) -> None:
        code = str(value or "").strip()
        if not code or code in seen:
            return
        seen.add(code)
        codes.append(code)

    if not isinstance(job_functions, list):
        return ()
    for job_function in job_functions:
        if not isinstance(job_function, Mapping):
            continue
        add_code(job_function.get("code"))
        children = job_function.get("children")
        if not isinstance(children, list):
            continue
        for child in children:
            if isinstance(child, Mapping):
                add_code(child.get("code"))
    return tuple(codes)


def _row_evidence(parsed_row: dict[str, Any]) -> ListingRowEvidence:
    title = str(parsed_row.get("title") or "").strip()
    return ListingRowEvidence(
        job_id=_normalized_optional_id(parsed_row.get("job_id")),
        encrypted_job_id=_normalized_optional_id(parsed_row.get("encrypted_job_id")),
        title=title,
        job_function_codes=_job_function_codes(parsed_row.get("job_functions")),
        title_language=_classify_title_language(title),
        api_language="zh_HK",
    )


def listing_observation_to_payload(value: Any) -> Any:
    """Recursively convert listing evidence values to JSON-safe primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return listing_observation_to_payload(asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): listing_observation_to_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [listing_observation_to_payload(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Unsupported listing observation value: {type(value).__name__}")


class OfferTodayListingRunner:
    def __init__(
        self,
        transport: OfferTodayListingTransport,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._clock = clock

    async def run(
        self,
        *,
        conditions: Sequence[OfferTodayListingCondition],
        stop_policy: ListingStopPolicy,
        retry_policy: ListingRetryPolicy,
        observation_sink: ListingObservationSink,
        staging_sink: ListingStagingSink,
        session_mode: str,
    ) -> ListingRunResult:
        observations: list[ListingPageObservation] = []
        outcomes: list[ListingConditionOutcome] = []
        gaps: list[ListingGap] = []
        ordered_job_ids: list[str] = []
        ordered_job_id_set: set[str] = set()
        accepted_job_ids: set[str] = set()
        job_to_encrypted_id: dict[str, str] = {}
        encrypted_id_to_job: dict[str, str] = {}
        staged_pair_values: set[tuple[str, str]] = set()
        deferred_job_ids: set[str] = set()
        identity_conflicts: list[ListingIdentityConflict] = []
        identity_conflict_keys: set[tuple[tuple[str, ...], tuple[str, ...], str]] = (
            set()
        )
        identity_issues: list[ListingIdentityIssue] = []
        run_stop_reason: str | None = None

        for condition in conditions:
            page = 1
            pages_observed = 0
            awaiting_empty_confirmation = False
            condition_stop_reason: str | None = None
            condition_is_complete = False

            while condition_stop_reason is None:
                if page > stop_policy.max_pages_per_condition:
                    condition_stop_reason = "page_cap"
                    break

                payload = build_offertoday_listing_payload(
                    category_id=condition.category_id,
                    keyword=condition.keyword,
                    page=page,
                    rcd_type=condition.rcd_type,
                )
                listing_url = _listing_url(condition)
                fingerprint = _request_fingerprint(listing_url, payload)
                page_succeeded = False

                for attempt in range(1, retry_policy.max_attempts_per_page + 1):
                    started_at = self._clock()
                    response: dict[str, Any] | None = None
                    transport_error: BaseException | None = None
                    current_url = listing_url
                    http_status: int | None = None
                    try:
                        response = await self._transport.fetch_listing_json(
                            payload,
                            listing_url=listing_url,
                        )
                    except Exception as exc:
                        transport_error = exc
                        error_payload = getattr(exc, "payload", None)
                        if isinstance(error_payload, Mapping):
                            response = dict(error_payload)
                        current_url = str(
                            getattr(exc, "response_url", None) or listing_url
                        )
                        raw_http_status = getattr(exc, "http_status", None)
                        if type(raw_http_status) is int:
                            http_status = raw_http_status

                    classification = classify_offertoday_response(
                        response,
                        operation="listing",
                        current_url=current_url,
                        transport_error=transport_error,
                        http_status=http_status,
                    )
                    latency_ms = int(round(max(0.0, self._clock() - started_at) * 1000))

                    if classification.kind is not OfferTodayResponseKind.SUCCESS:
                        will_retry = (
                            classification.retryable
                            and attempt < retry_policy.max_attempts_per_page
                        )
                        if classification.stop_batch:
                            attempt_stop_reason = classification.kind.value
                        elif will_retry:
                            attempt_stop_reason = None
                        else:
                            attempt_stop_reason = "unresolved_gap"

                        observation = self._empty_observation(
                            condition=condition,
                            page=page,
                            attempt=attempt,
                            request_fingerprint=fingerprint,
                            classification=classification,
                            latency_ms=latency_ms,
                            session_mode=session_mode,
                            retry_reason=(
                                classification.kind.value
                                if classification.retryable
                                else None
                            ),
                            stop_reason=attempt_stop_reason,
                        )
                        observations.append(observation)
                        await observation_sink.record_page_attempt(observation)

                        if classification.stop_batch:
                            condition_stop_reason = classification.kind.value
                            break
                        if will_retry:
                            delay = _retry_delay(retry_policy, attempt)
                            if delay > 0:
                                await self._sleep(delay)
                            continue

                        gaps.append(
                            ListingGap(
                                condition_id=condition.condition_id,
                                page=page,
                                attempts=attempt,
                                last_kind=classification.kind,
                            )
                        )
                        condition_stop_reason = "unresolved_gap"
                        break

                    if response is None:  # pragma: no cover - classifier invariant
                        raise AssertionError(
                            "success classification requires a response"
                        )

                    parsed_rows = parse_offertoday_listing_response(response)
                    raw_data = response.get("data")
                    if not isinstance(raw_data, Mapping):  # pragma: no cover
                        raise AssertionError("success listing response requires data")
                    raw_rows = raw_data.get("resultList")
                    if not isinstance(raw_rows, list):  # pragma: no cover
                        raise AssertionError(
                            "success listing response requires resultList"
                        )
                    raw_has_more = raw_data.get("hasMore")
                    has_more = raw_has_more if type(raw_has_more) is bool else None
                    raw_total = raw_data.get("total")
                    reported_total = raw_total if type(raw_total) is int else None
                    page_succeeded = True
                    pages_observed += 1

                    row_evidence = tuple(_row_evidence(row) for row in parsed_rows)
                    page_pairs: list[OfferTodayIdentityPair] = []
                    page_pair_values: set[tuple[str, str]] = set()
                    page_issues: list[ListingIdentityIssue] = []
                    page_conflicts: list[ListingIdentityConflict] = []
                    page_conflict_keys: set[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = set()
                    page_deferrals: list[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = []
                    page_deferral_keys: set[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = set()

                    def add_deferral(
                        job_ids: tuple[str, ...],
                        encrypted_job_ids: tuple[str, ...],
                        reason: str,
                    ) -> None:
                        key = (job_ids, encrypted_job_ids, reason)
                        if key in page_deferral_keys:
                            return
                        page_deferral_keys.add(key)
                        page_deferrals.append(key)

                    def add_conflict(conflict: ListingIdentityConflict) -> None:
                        key = (
                            conflict.job_ids,
                            conflict.encrypted_job_ids,
                            conflict.reason,
                        )
                        if key not in page_conflict_keys:
                            page_conflict_keys.add(key)
                            page_conflicts.append(conflict)
                            add_deferral(*key)
                        if key not in identity_conflict_keys:
                            identity_conflict_keys.add(key)
                            identity_conflicts.append(conflict)

                    for evidence in row_evidence:
                        job_id = evidence.job_id
                        encrypted_job_id = evidence.encrypted_job_id
                        if job_id is not None and job_id not in ordered_job_id_set:
                            ordered_job_id_set.add(job_id)
                            ordered_job_ids.append(job_id)

                        if job_id is None:
                            issue = ListingIdentityIssue(
                                job_id=None,
                                encrypted_job_id=encrypted_job_id,
                                reason="missing_job_id",
                            )
                            page_issues.append(issue)
                            identity_issues.append(issue)
                            continue
                        if encrypted_job_id is None:
                            issue = ListingIdentityIssue(
                                job_id=job_id,
                                encrypted_job_id=None,
                                reason="missing_encrypted_job_id",
                            )
                            page_issues.append(issue)
                            identity_issues.append(issue)
                            accepted_job_ids.discard(job_id)
                            deferred_job_ids.add(job_id)
                            known_encrypted_job_id = job_to_encrypted_id.get(job_id)
                            if known_encrypted_job_id is not None:
                                add_deferral(
                                    (job_id,),
                                    (known_encrypted_job_id,),
                                    issue.reason,
                                )
                            continue

                        pair_value = (job_id, encrypted_job_id)
                        if pair_value not in page_pair_values:
                            page_pair_values.add(pair_value)
                            page_pairs.append(OfferTodayIdentityPair(*pair_value))

                        known_encrypted_job_id = job_to_encrypted_id.get(job_id)
                        if (
                            known_encrypted_job_id is not None
                            and known_encrypted_job_id != encrypted_job_id
                        ):
                            add_conflict(
                                ListingIdentityConflict(
                                    job_ids=(job_id,),
                                    encrypted_job_ids=(
                                        known_encrypted_job_id,
                                        encrypted_job_id,
                                    ),
                                    reason="one_job_id_to_multiple_encrypted_ids",
                                )
                            )

                        known_job_id = encrypted_id_to_job.get(encrypted_job_id)
                        if known_job_id is not None and known_job_id != job_id:
                            add_conflict(
                                ListingIdentityConflict(
                                    job_ids=(known_job_id, job_id),
                                    encrypted_job_ids=(encrypted_job_id,),
                                    reason="one_encrypted_id_to_multiple_job_ids",
                                )
                            )

                        job_to_encrypted_id.setdefault(job_id, encrypted_job_id)
                        encrypted_id_to_job.setdefault(encrypted_job_id, job_id)

                    for conflict in page_conflicts:
                        for conflicted_job_id in conflict.job_ids:
                            deferred_job_ids.add(conflicted_job_id)
                            accepted_job_ids.discard(conflicted_job_id)

                    for evidence in row_evidence:
                        if (
                            evidence.job_id is not None
                            and evidence.encrypted_job_id is not None
                            and evidence.job_id not in deferred_job_ids
                        ):
                            accepted_job_ids.add(evidence.job_id)

                    stage_rows: list[dict[str, Any]] = []
                    stage_pair_values: list[tuple[str, str]] = []
                    page_stage_pair_values: set[tuple[str, str]] = set()
                    if not page_issues and not page_conflicts:
                        for parsed_row, evidence in zip(parsed_rows, row_evidence):
                            if (
                                evidence.job_id is None
                                or evidence.encrypted_job_id is None
                            ):
                                continue
                            pair_value = (
                                evidence.job_id,
                                evidence.encrypted_job_id,
                            )
                            if (
                                pair_value in staged_pair_values
                                or pair_value in page_stage_pair_values
                            ):
                                continue
                            page_stage_pair_values.add(pair_value)
                            stage_pair_values.append(pair_value)
                            stage_rows.append(parsed_row)

                    is_nonempty_confirmation = awaiting_empty_confirmation and bool(
                        raw_rows
                    )
                    terminal_signal = not raw_rows or has_more is False
                    natural_exhaustion = (
                        awaiting_empty_confirmation and not raw_rows
                    ) or (
                        not stop_policy.require_empty_confirmation and terminal_signal
                    )

                    if page_conflicts:
                        attempt_stop_reason = "identity_conflict"
                        condition_stop_reason = "identity_conflict"
                    elif page_issues:
                        attempt_stop_reason = "identity_issue"
                        condition_stop_reason = "identity_issue"
                    elif natural_exhaustion:
                        attempt_stop_reason = "natural_exhaustion"
                        condition_stop_reason = "natural_exhaustion"
                        condition_is_complete = True
                    else:
                        if awaiting_empty_confirmation:
                            awaiting_empty_confirmation = False
                        if terminal_signal:
                            awaiting_empty_confirmation = True

                        if (
                            stop_policy.unique_job_cap is not None
                            and len(ordered_job_ids) >= stop_policy.unique_job_cap
                        ):
                            attempt_stop_reason = "target_cap"
                            condition_stop_reason = "target_cap"
                        elif page >= stop_policy.max_pages_per_condition:
                            attempt_stop_reason = "page_cap"
                            condition_stop_reason = "page_cap"
                        else:
                            attempt_stop_reason = None

                    observation = ListingPageObservation(
                        condition_id=condition.condition_id,
                        search_family=condition.search_family,
                        category_id=condition.category_id,
                        keyword=condition.keyword,
                        endpoint=condition.endpoint,
                        rcd_type=condition.rcd_type,
                        page=page,
                        attempt=attempt,
                        request_fingerprint=fingerprint,
                        classification=(
                            "contract_anomaly"
                            if is_nonempty_confirmation
                            else classification.kind.value
                        ),
                        api_code=classification.code,
                        reported_total=reported_total,
                        has_more=has_more,
                        row_count=len(raw_rows),
                        missing_job_id_count=sum(
                            evidence.job_id is None for evidence in row_evidence
                        ),
                        missing_encrypted_job_id_count=sum(
                            evidence.encrypted_job_id is None
                            for evidence in row_evidence
                        ),
                        id_pairs=tuple(page_pairs),
                        rows=row_evidence,
                        identity_issues=tuple(page_issues),
                        identity_conflicts=tuple(page_conflicts),
                        latency_ms=latency_ms,
                        session_mode=session_mode,
                        retry_reason=None,
                        stop_reason=attempt_stop_reason,
                    )
                    observations.append(observation)
                    await observation_sink.record_page_attempt(observation)
                    for job_ids, encrypted_job_ids, reason in page_deferrals:
                        await staging_sink.defer_identity_conflict(
                            job_ids=job_ids,
                            encrypted_job_ids=encrypted_job_ids,
                            reason=reason,
                        )
                    if stage_rows:
                        await staging_sink.stage_page(
                            condition=condition,
                            page=page,
                            rows=stage_rows,
                        )
                        staged_pair_values.update(stage_pair_values)
                    break

                if condition_stop_reason is not None:
                    break
                if not page_succeeded:  # pragma: no cover - retry loop invariant
                    raise AssertionError("page loop ended without an outcome")
                page += 1
                if retry_policy.page_delay_seconds > 0:
                    await self._sleep(retry_policy.page_delay_seconds)

            outcome = ListingConditionOutcome(
                condition=condition,
                pages_observed=pages_observed,
                stop_reason=condition_stop_reason or "condition_incomplete",
                is_complete=condition_is_complete,
            )
            outcomes.append(outcome)
            await observation_sink.record_condition_outcome(outcome)
            if not condition_is_complete:
                run_stop_reason = outcome.stop_reason
                break

        is_complete = (
            len(outcomes) == len(conditions)
            and all(outcome.is_complete for outcome in outcomes)
            and not gaps
            and not identity_conflicts
            and not identity_issues
        )
        if is_complete:
            run_stop_reason = "natural_exhaustion"

        return ListingRunResult(
            ordered_job_ids=tuple(ordered_job_ids),
            accepted_job_ids=tuple(
                job_id for job_id in ordered_job_ids if job_id in accepted_job_ids
            ),
            id_pairs=tuple(
                OfferTodayIdentityPair(
                    job_id=job_id,
                    encrypted_job_id=job_to_encrypted_id[job_id],
                )
                for job_id in ordered_job_ids
                if job_id in accepted_job_ids and job_id in job_to_encrypted_id
            ),
            observations=tuple(observations),
            condition_outcomes=tuple(outcomes),
            identity_conflicts=tuple(identity_conflicts),
            identity_issues=tuple(identity_issues),
            gaps=tuple(gaps),
            stop_reason=run_stop_reason or "condition_incomplete",
            is_complete=is_complete,
        )

    @staticmethod
    def _empty_observation(
        *,
        condition: OfferTodayListingCondition,
        page: int,
        attempt: int,
        request_fingerprint: str,
        classification: OfferTodayResponseClassification,
        latency_ms: int,
        session_mode: str,
        retry_reason: str | None,
        stop_reason: str | None,
    ) -> ListingPageObservation:
        return ListingPageObservation(
            condition_id=condition.condition_id,
            search_family=condition.search_family,
            category_id=condition.category_id,
            keyword=condition.keyword,
            endpoint=condition.endpoint,
            rcd_type=condition.rcd_type,
            page=page,
            attempt=attempt,
            request_fingerprint=request_fingerprint,
            classification=classification.kind.value,
            api_code=classification.code,
            reported_total=None,
            has_more=None,
            row_count=0,
            missing_job_id_count=0,
            missing_encrypted_job_id_count=0,
            id_pairs=(),
            rows=(),
            identity_issues=(),
            identity_conflicts=(),
            latency_ms=latency_ms,
            session_mode=session_mode,
            retry_reason=retry_reason,
            stop_reason=stop_reason,
        )
