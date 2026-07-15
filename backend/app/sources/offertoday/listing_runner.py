from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
    _validate_offertoday_rcd_type,
    build_offertoday_listing_payload,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
    OfferTodayIdentityError,
    build_offertoday_identity_authority_index,
    resolve_offertoday_listing_identity,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayBrowserContextLostError,
    OfferTodayCursorContractError,
    OfferTodayListingCursor,
    OfferTodayListingCursorFieldPresence,
    OfferTodayListingIdentityEvidenceV2,
    OfferTodayListingPageEvidenceV2,
    OfferTodayListingRequestPolicy,
    OfferTodayListingTransportResult,
    offertoday_listing_cursor_field_presence,
    parse_offertoday_listing_page_result,
    validate_offertoday_endpoint_request,
    validate_offertoday_endpoint_response_url,
)
from app.sources.offertoday.parsers import (
    parse_offertoday_listing_response,
    parse_offertoday_listing_rows,
)
from app.sources.offertoday.response_policy import (
    OfferTodayResponseClassification,
    OfferTodayResponseKind,
    OfferTodayTransportError,
    classify_offertoday_response,
)


_MAX_BROWSER_CONTEXT_RESTARTS_PER_CONDITION = 1
ENVELOPE_TERMINAL_POLICY_ID = "cursor-terminal-empty-confirmation-v1"
RESULT_TERMINAL_POLICY_ID = "result-transition-confirmation-v1"
RESULT_TERMINAL_CONFIRMATION_PAGE_COUNT = 2
ListingTerminalPolicy = Literal[
    "cursor-terminal-empty-confirmation-v1",
    "result-transition-confirmation-v1",
]
ListingPageCapBehavior = Literal["reject", "retain-and-continue"]


@dataclass(frozen=True, slots=True)
class OfferTodayListingCondition:
    search_family: str
    category_id: int | None
    keyword: str
    endpoint: Literal["search", "browse"]
    rcd_type: int | None = 7

    def __post_init__(self) -> None:
        if self.endpoint not in ("search", "browse"):
            raise ValueError("endpoint must be 'search' or 'browse'")
        _validate_offertoday_rcd_type(self.rcd_type)

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
    page_cap_behavior: ListingPageCapBehavior = "reject"

    def __post_init__(self) -> None:
        if self.max_pages_per_condition < 1:
            raise ValueError("max_pages_per_condition must be >= 1")
        if self.page_cap_behavior not in {"reject", "retain-and-continue"}:
            raise ValueError(
                "page_cap_behavior must be 'reject' or 'retain-and-continue'"
            )


@dataclass(frozen=True, slots=True)
class ListingRetryPolicy:
    max_attempts_per_page: int = 3
    retry_delays_seconds: tuple[float, ...] = (1.0, 2.0)
    page_delay_seconds: float = 0.0
    page_delay_range_seconds: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.max_attempts_per_page < 1:
            raise ValueError("max_attempts_per_page must be >= 1")
        if self.page_delay_range_seconds is not None:
            lower, upper = self.page_delay_range_seconds
            if (
                type(lower) not in (int, float)
                or type(upper) not in (int, float)
                or not math.isfinite(lower)
                or not math.isfinite(upper)
                or lower < 0
                or upper < 0
                or lower > upper
            ):
                raise ValueError(
                    "page_delay_range_seconds must contain finite non-negative "
                    "values with lower <= upper"
                )


@dataclass(frozen=True, slots=True)
class OfferTodayIdentityPair:
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"


@dataclass(frozen=True, slots=True)
class ListingIdentityIssue:
    job_id: str | None
    encrypted_job_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ListingRowEvidence:
    job_id: str | None
    encrypted_job_id: str | None
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None
    observed_encrypted_job_id: str | None
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
    job_id_fallback_count: int
    id_pairs: tuple[OfferTodayIdentityPair, ...]
    rows: tuple[ListingRowEvidence, ...]
    identity_issues: tuple[ListingIdentityIssue, ...]
    identity_conflicts: tuple[ListingIdentityConflict, ...]
    latency_ms: int
    session_mode: str
    retry_reason: str | None
    stop_reason: str | None
    supplemental_identity_issues: tuple[ListingIdentityIssue, ...] = ()
    supplemental_identity_conflicts: tuple[ListingIdentityConflict, ...] = ()
    cursor_evidence: OfferTodayListingPageEvidenceV2 | None = None
    response_url: str | None = None


@dataclass(frozen=True, slots=True)
class ListingConditionOutcome:
    condition: OfferTodayListingCondition
    pages_observed: int
    stop_reason: str
    is_complete: bool
    is_partial: bool = False


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
    is_partial: bool = False
    capped_condition_ids: tuple[str, ...] = ()
    supplemental_rows_observed: int = 0
    supplemental_job_ids: tuple[str, ...] = ()
    supplemental_identity_issue_count: int = 0

    @property
    def is_partial_success(self) -> bool:
        return (
            self.is_partial
            and len(self.condition_outcomes) > 0
            and all(
                outcome.is_complete or outcome.is_partial
                for outcome in self.condition_outcomes
            )
            and not self.gaps
            and not self.identity_conflicts
            and not self.identity_issues
        )

    @property
    def can_proceed_to_detail(self) -> bool:
        return self.is_complete or self.is_partial_success


@dataclass(frozen=True, slots=True)
class _ListingRowIdentityAnalysis:
    identity: OfferTodayDetailIdentity | None
    evidence: ListingRowEvidence
    issue: ListingIdentityIssue | None
    job_id_issue_reason: str | None
    encrypted_job_id_issue_reason: str | None


class OfferTodayListingTransport(Protocol):
    async def fetch_listing_json(
        self,
        payload: dict[str, Any],
        *,
        listing_url: str | None = None,
    ) -> dict[str, Any] | OfferTodayListingTransportResult | None: ...


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


def offertoday_listing_request_fingerprint(
    listing_url: str,
    payload: dict[str, Any],
    *,
    cursor_hash: str | None = None,
) -> str:
    fingerprint_payload = dict(payload)
    for field_name in (
        "sessionId",
        "supplePage",
        "suppleAmount",
        "suppleType",
    ):
        fingerprint_payload.pop(field_name, None)
    if cursor_hash is not None:
        fingerprint_payload["cursorHash"] = cursor_hash
    canonical_json = json.dumps(
        {"payload": fingerprint_payload, "url": listing_url},
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


def _analyze_raw_identity_value(
    value: Any,
    *,
    missing_reason: str,
    invalid_reason: str,
) -> tuple[str | None, str | None]:
    if value is None:
        return None, missing_reason
    if type(value) is not str:
        return None, invalid_reason
    normalized = value.strip()
    if not normalized:
        return None, missing_reason
    return normalized, None


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


def _analyze_listing_row(
    parsed_row: dict[str, Any],
) -> _ListingRowIdentityAnalysis:
    raw_data = parsed_row.get("raw_data")
    raw_data = raw_data if isinstance(raw_data, Mapping) else {}
    raw_job_id, job_issue_reason = _analyze_raw_identity_value(
        raw_data.get("jobId"),
        missing_reason="missing_job_id",
        invalid_reason="invalid_job_id",
    )
    observed_encrypted_job_id, encrypted_issue_reason = _analyze_raw_identity_value(
        raw_data.get("encryptJobId"),
        missing_reason="missing_encrypted_job_id",
        invalid_reason="invalid_encrypted_job_id",
    )
    identity: OfferTodayDetailIdentity | None = None
    resolver_issue: ListingIdentityIssue | None = None
    try:
        identity = resolve_offertoday_listing_identity(raw_data)
    except OfferTodayIdentityError as exc:
        resolver_issue = ListingIdentityIssue(
            job_id=raw_job_id,
            encrypted_job_id=observed_encrypted_job_id,
            reason=exc.classification,
        )
    title = str(parsed_row.get("title") or "").strip()
    evidence = ListingRowEvidence(
        job_id=identity.job_id if identity is not None else raw_job_id,
        encrypted_job_id=(
            identity.encrypted_job_id
            if identity is not None
            else observed_encrypted_job_id
        ),
        encrypted_job_id_source=(
            identity.encrypted_job_id_source if identity is not None else None
        ),
        observed_encrypted_job_id=observed_encrypted_job_id,
        title=title,
        job_function_codes=_job_function_codes(parsed_row.get("job_functions")),
        title_language=_classify_title_language(title),
        api_language="zh_HK",
    )
    return _ListingRowIdentityAnalysis(
        identity=identity,
        evidence=evidence,
        issue=resolver_issue,
        job_id_issue_reason=job_issue_reason,
        encrypted_job_id_issue_reason=encrypted_issue_reason,
    )


def listing_observation_to_payload(value: Any) -> Any:
    """Recursively convert listing evidence values to JSON-safe primitives."""
    if isinstance(value, ListingPageObservation):
        payload = asdict(value)
        if value.cursor_evidence is None:
            payload.pop("cursor_evidence", None)
        payload.pop("supplemental_identity_issues", None)
        payload.pop("supplemental_identity_conflicts", None)
        # Historical research artifacts have a frozen key set. Production
        # events add this transport field explicitly at their own boundary.
        payload.pop("response_url", None)
        return listing_observation_to_payload(payload)
    if isinstance(value, ListingConditionOutcome):
        payload = asdict(value)
        if not value.is_partial:
            payload.pop("is_partial", None)
        return listing_observation_to_payload(payload)
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


def _browser_context_hash(transport: Any) -> str | None:
    value = getattr(transport, "browser_context_hash", None)
    return value if isinstance(value, str) and value else None


def _v2_page_evidence(
    *,
    policy: OfferTodayListingRequestPolicy,
    condition: OfferTodayListingCondition,
    page: int,
    attempt: int,
    browser_context_hash: str | None,
    cursor_input: OfferTodayListingCursor | None,
    cursor_output: OfferTodayListingCursor | None,
    response_page_size: int | None,
    response_cursor_fields: OfferTodayListingCursorFieldPresence | None = None,
    result_job_ids: Sequence[str] = (),
    supplemental_job_ids: Sequence[str] = (),
    result_identity_pairs: Sequence[OfferTodayListingIdentityEvidenceV2] = (),
    supplemental_identity_pairs: Sequence[
        OfferTodayListingIdentityEvidenceV2
    ] = (),
    result_row_count: int | None = None,
    supplemental_row_count: int | None = None,
    previously_seen_job_ids: set[str] | None = None,
    terminal_signal: bool = False,
    awaiting_empty_confirmation: bool = False,
    contract_error: str | None = None,
) -> OfferTodayListingPageEvidenceV2:
    result_ids = tuple(str(value) for value in result_job_ids if str(value))
    supplemental_ids = tuple(
        str(value) for value in supplemental_job_ids if str(value)
    )
    all_ids = (*result_ids, *supplemental_ids)
    seen = set(previously_seen_job_ids or ())
    page_ids = set(all_ids)
    new_ids = page_ids - seen
    effective_page_size = (
        cursor_output.effective_page_size
        if cursor_output is not None
        else response_page_size
    )
    if policy.pagination_mode == "stateless-control":
        session_continuity = "not_applicable"
    elif contract_error is not None:
        session_continuity = (
            "violation"
            if contract_error in {"session_rollover", "page_size_drift"}
            else "unavailable"
        )
    elif cursor_output is None:
        session_continuity = "unavailable"
    elif cursor_input is None:
        session_continuity = "initial"
    elif cursor_input.session_id == cursor_output.session_id:
        session_continuity = "continued"
    else:  # pragma: no cover - parser rejects rollover first
        session_continuity = "violation"
    resolved_result_row_count = (
        len(result_ids) if result_row_count is None else result_row_count
    )
    resolved_supplemental_row_count = (
        len(supplemental_ids)
        if supplemental_row_count is None
        else supplemental_row_count
    )
    full_row_count = resolved_result_row_count + resolved_supplemental_row_count
    return OfferTodayListingPageEvidenceV2(
        protocol_version=policy.protocol_version,
        variant_id=policy.variant_id,
        repeat_index=policy.repeat_index,
        condition_restart_index=policy.condition_restart_index,
        condition_execution_id=policy.condition_execution_id(condition.condition_id),
        logical_request_id=policy.logical_request_id(condition.condition_id, page),
        physical_attempt_id=policy.physical_attempt_id(
            condition.condition_id,
            page,
            attempt,
        ),
        browser_context_hash=browser_context_hash,
        pagination_mode=policy.pagination_mode,
        browser_lifecycle=policy.browser_lifecycle,
        requested_page_size=policy.requested_page_size,
        response_page_size=response_page_size,
        effective_page_size=effective_page_size,
        cursor_input=cursor_input.to_evidence() if cursor_input is not None else None,
        cursor_output=(
            cursor_output.to_evidence() if cursor_output is not None else None
        ),
        response_cursor_fields=(
            response_cursor_fields
            if response_cursor_fields is not None
            else OfferTodayListingCursorFieldPresence(
                session_id=False,
                supple_page=False,
                supple_amount=False,
                supple_type=False,
                page_size=False,
            )
        ),
        session_continuity=session_continuity,
        result_row_count=resolved_result_row_count,
        supplemental_row_count=resolved_supplemental_row_count,
        result_job_ids=result_ids,
        supplemental_job_ids=supplemental_ids,
        result_identity_pairs=tuple(result_identity_pairs),
        supplemental_identity_pairs=tuple(supplemental_identity_pairs),
        cohort_overlap_job_ids=tuple(sorted(set(result_ids) & set(supplemental_ids))),
        new_job_id_count=len(new_ids),
        duplicate_job_id_count=max(0, len(all_ids) - len(new_ids)),
        zero_new_full_page=(
            effective_page_size is not None
            and full_row_count >= effective_page_size
            and not new_ids
        ),
        terminal_signal=terminal_signal,
        awaiting_empty_confirmation=awaiting_empty_confirmation,
        contract_error=contract_error,
    )


class OfferTodayListingRunner:
    def __init__(
        self,
        transport: OfferTodayListingTransport,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.perf_counter,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._uniform = uniform

    async def run(
        self,
        *,
        conditions: Sequence[OfferTodayListingCondition],
        stop_policy: ListingStopPolicy,
        retry_policy: ListingRetryPolicy,
        observation_sink: ListingObservationSink,
        staging_sink: ListingStagingSink,
        session_mode: str,
        request_policy: OfferTodayListingRequestPolicy | None = None,
        terminal_policy: ListingTerminalPolicy = ENVELOPE_TERMINAL_POLICY_ID,
    ) -> ListingRunResult:
        if terminal_policy not in {
            ENVELOPE_TERMINAL_POLICY_ID,
            RESULT_TERMINAL_POLICY_ID,
        }:
            raise ValueError("unsupported listing terminal policy")
        if terminal_policy == RESULT_TERMINAL_POLICY_ID and (
            request_policy is None or not request_policy.requires_cursor
        ):
            raise ValueError("result terminal policy requires response-cursor mode")
        observations: list[ListingPageObservation] = []
        outcomes: list[ListingConditionOutcome] = []
        gaps: list[ListingGap] = []
        ordered_job_ids: list[str] = []
        ordered_job_id_set: set[str] = set()
        accepted_job_ids: set[str] = set()
        job_to_identity: dict[str, OfferTodayDetailIdentity] = {}
        staged_identity_values: set[
            tuple[str, str, OfferTodayEncryptedJobIdSource]
        ] = set()
        deferred_job_ids: set[str] = set()
        identity_conflicts: list[ListingIdentityConflict] = []
        identity_conflict_keys: set[tuple[tuple[str, ...], tuple[str, ...], str]] = (
            set()
        )
        identity_issues: list[ListingIdentityIssue] = []
        supplemental_rows_observed = 0
        supplemental_job_ids: list[str] = []
        supplemental_job_id_set: set[str] = set()
        supplemental_identity_issue_count = 0
        capped_condition_ids: list[str] = []
        run_stop_reason: str | None = None

        for condition in conditions:
            condition_ordered_job_count = len(ordered_job_ids)
            condition_accepted_job_ids = set(accepted_job_ids)
            condition_job_to_identity = dict(job_to_identity)
            condition_staged_identity_values = set(staged_identity_values)
            page = 1
            pages_observed = 0
            awaiting_empty_confirmation = False
            condition_stop_reason: str | None = None
            condition_is_complete = False
            condition_is_partial = False
            cursor: OfferTodayListingCursor | None = None
            initial_session_id: str | None = None
            effective_page_size: int | None = None
            v2_seen_job_ids: set[str] = set()
            pending_v2_stage_pages: list[tuple[int, list[dict[str, Any]]]] = []
            active_request_policy = request_policy
            active_endpoint_contract = (
                active_request_policy.endpoint_contract
                if active_request_policy is not None
                else None
            )
            if (
                active_endpoint_contract is not None
                and active_endpoint_contract.endpoint != condition.endpoint
            ):
                raise ValueError(
                    "endpoint contract does not match listing condition endpoint"
                )
            condition_restart_count = 0
            logical_pages_started = 0
            result_empty_confirmation_count = 0

            while condition_stop_reason is None:
                if active_request_policy is not None:
                    if logical_pages_started >= stop_policy.max_pages_per_condition:
                        condition_stop_reason = "page_cap"
                        condition_is_partial = (
                            stop_policy.page_cap_behavior == "retain-and-continue"
                        )
                        break
                    logical_pages_started += 1
                elif page > stop_policy.max_pages_per_condition:
                    condition_stop_reason = "page_cap"
                    condition_is_partial = (
                        stop_policy.page_cap_behavior == "retain-and-continue"
                    )
                    break

                payload = build_offertoday_listing_payload(
                    category_id=condition.category_id,
                    keyword=condition.keyword,
                    page=page,
                    rcd_type=condition.rcd_type,
                    page_size=(
                        active_request_policy.requested_page_size
                        if active_request_policy is not None
                        else 50
                    ),
                    cursor=(
                        cursor
                        if active_request_policy is not None
                        and active_request_policy.requires_cursor
                        and page > 1
                        else None
                    ),
                )
                listing_url = _listing_url(condition)
                if active_endpoint_contract is not None:
                    if active_endpoint_contract.url != listing_url:
                        raise ValueError(
                            "endpoint contract URL does not match listing condition URL"
                        )
                    validate_offertoday_endpoint_request(
                        active_endpoint_contract,
                        payload,
                    )
                fingerprint = offertoday_listing_request_fingerprint(
                    listing_url,
                    payload,
                    cursor_hash=(cursor.cursor_hash if cursor is not None else None),
                )
                page_succeeded = False
                restart_condition = False

                for attempt in range(1, retry_policy.max_attempts_per_page + 1):
                    record_page_start = getattr(
                        observation_sink,
                        "record_page_start",
                        None,
                    )
                    if callable(record_page_start):
                        await record_page_start(
                            condition=condition,
                            page=page,
                            attempt=attempt,
                            max_attempts=retry_policy.max_attempts_per_page,
                        )
                    started_at = self._clock()
                    response: dict[str, Any] | None = None
                    browser_context_hash = _browser_context_hash(self._transport)
                    transport_error: BaseException | None = None
                    current_url = listing_url
                    http_status: int | None = None
                    try:
                        typed_fetch = getattr(
                            self._transport,
                            "fetch_listing_page",
                            None,
                        )
                        if active_request_policy is not None and callable(typed_fetch):
                            transport_result = await typed_fetch(
                                payload,
                                listing_url=listing_url,
                            )
                        else:
                            transport_result = (
                                await self._transport.fetch_listing_json(
                                    payload,
                                    listing_url=listing_url,
                                )
                            )
                        if isinstance(
                            transport_result,
                            OfferTodayListingTransportResult,
                        ):
                            response = transport_result.payload
                            current_url = (
                                transport_result.response_url or current_url
                            )
                            http_status = transport_result.http_status
                            browser_context_hash = (
                                transport_result.browser_context_hash
                                or browser_context_hash
                            )
                        else:
                            response = transport_result
                    except (
                        OfferTodayTransportError,
                        TimeoutError,
                        ConnectionError,
                    ) as exc:
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

                    browser_context_hash = (
                        _browser_context_hash(self._transport)
                        or browser_context_hash
                    )

                    classification = classify_offertoday_response(
                        response,
                        operation="listing",
                        current_url=current_url,
                        transport_error=transport_error,
                        http_status=http_status,
                    )
                    latency_ms = int(round(max(0.0, self._clock() - started_at) * 1000))

                    browser_context_lost = isinstance(
                        transport_error,
                        OfferTodayBrowserContextLostError,
                    )
                    if browser_context_lost and active_request_policy is not None:
                        restart_transport = getattr(
                            self._transport,
                            "restart_after_browser_loss",
                            None,
                        )
                        can_restart = (
                            callable(restart_transport)
                            and condition_restart_count
                            < _MAX_BROWSER_CONTEXT_RESTARTS_PER_CONDITION
                        )
                        observation = self._empty_observation(
                            condition=condition,
                            page=page,
                            attempt=attempt,
                            request_fingerprint=fingerprint,
                            classification=classification,
                            latency_ms=latency_ms,
                            session_mode=session_mode,
                            retry_reason=(
                                "browser_context_lost_restart"
                                if can_restart
                                else None
                            ),
                            stop_reason=(None if can_restart else "unresolved_gap"),
                            response_url=current_url,
                            cursor_evidence=_v2_page_evidence(
                                policy=active_request_policy,
                                condition=condition,
                                page=page,
                                attempt=attempt,
                                browser_context_hash=browser_context_hash,
                                cursor_input=cursor,
                                cursor_output=None,
                                response_page_size=None,
                                previously_seen_job_ids=v2_seen_job_ids,
                                awaiting_empty_confirmation=(
                                    awaiting_empty_confirmation
                                ),
                            ),
                        )
                        observations.append(observation)
                        await observation_sink.record_page_attempt(observation)
                        if can_restart:
                            await restart_transport()
                            condition_restart_count += 1
                            active_request_policy = replace(
                                active_request_policy,
                                condition_restart_index=condition_restart_count,
                            )
                            page = 1
                            cursor = None
                            initial_session_id = None
                            effective_page_size = None
                            awaiting_empty_confirmation = False
                            result_empty_confirmation_count = 0
                            restart_condition = True
                            break
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
                                classification.kind.value if will_retry else None
                            ),
                            stop_reason=attempt_stop_reason,
                            response_url=current_url,
                            cursor_evidence=(
                                _v2_page_evidence(
                                    policy=active_request_policy,
                                    condition=condition,
                                    page=page,
                                    attempt=attempt,
                                    browser_context_hash=browser_context_hash,
                                    cursor_input=cursor,
                                    cursor_output=None,
                                    response_page_size=None,
                                    previously_seen_job_ids=v2_seen_job_ids,
                                    awaiting_empty_confirmation=(
                                        awaiting_empty_confirmation
                                    ),
                                    contract_error=(
                                        classification.kind.value
                                        if not will_retry
                                        else None
                                    ),
                                )
                                if active_request_policy is not None
                                else None
                            ),
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

                    if active_endpoint_contract is not None:
                        try:
                            validate_offertoday_endpoint_response_url(
                                active_endpoint_contract,
                                current_url,
                            )
                        except OfferTodayCursorContractError as exc:
                            observation = self._empty_observation(
                                condition=condition,
                                page=page,
                                attempt=attempt,
                                request_fingerprint=fingerprint,
                                classification=classification,
                                latency_ms=latency_ms,
                                session_mode=session_mode,
                                retry_reason=None,
                                stop_reason="endpoint_contract_violation",
                                response_url=current_url,
                                cursor_evidence=_v2_page_evidence(
                                    policy=active_request_policy,
                                    condition=condition,
                                    page=page,
                                    attempt=attempt,
                                    browser_context_hash=browser_context_hash,
                                    cursor_input=cursor,
                                    cursor_output=None,
                                    response_page_size=None,
                                    previously_seen_job_ids=v2_seen_job_ids,
                                    awaiting_empty_confirmation=(
                                        awaiting_empty_confirmation
                                    ),
                                    contract_error=exc.reason,
                                ),
                            )
                            observations.append(observation)
                            await observation_sink.record_page_attempt(observation)
                            condition_stop_reason = "endpoint_contract_violation"
                            break

                    page_contract = None
                    next_cursor: OfferTodayListingCursor | None = None
                    raw_supplemental_rows: list[dict[str, Any]] = []
                    if active_request_policy is not None:
                        try:
                            page_contract = parse_offertoday_listing_page_result(
                                response,
                                require_cursor=active_request_policy.requires_cursor,
                                expected_session_id=(
                                    initial_session_id
                                    if active_request_policy.requires_cursor
                                    else None
                                ),
                                expected_effective_page_size=(
                                    effective_page_size
                                    if active_request_policy.requires_cursor
                                    else None
                                ),
                                endpoint_contract_id=(
                                    active_request_policy.endpoint_contract_id
                                ),
                            )
                        except OfferTodayCursorContractError as exc:
                            raw_data = response.get("data")
                            raw_page_size = (
                                raw_data.get("pageSize")
                                if isinstance(raw_data, Mapping)
                                else None
                            )
                            response_page_size = (
                                raw_page_size
                                if type(raw_page_size) is int and raw_page_size > 0
                                else None
                            )
                            endpoint_violation = (
                                active_endpoint_contract is not None
                                and exc.reason
                                in {
                                    "unverified_cursor_contract",
                                    "unexpected_search_cursor_fields",
                                    "unexpected_search_supplemental_rows",
                                }
                            )
                            violation_stop_reason = (
                                "endpoint_contract_violation"
                                if endpoint_violation
                                else "cursor_contract_violation"
                            )
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
                                classification=violation_stop_reason,
                                api_code=classification.code,
                                reported_total=None,
                                has_more=None,
                                row_count=0,
                                missing_job_id_count=0,
                                missing_encrypted_job_id_count=0,
                                job_id_fallback_count=0,
                                id_pairs=(),
                                rows=(),
                                identity_issues=(),
                                identity_conflicts=(),
                                latency_ms=latency_ms,
                                session_mode=session_mode,
                                retry_reason=None,
                                stop_reason=violation_stop_reason,
                                response_url=current_url,
                                cursor_evidence=_v2_page_evidence(
                                    policy=active_request_policy,
                                    condition=condition,
                                    page=page,
                                    attempt=attempt,
                                    browser_context_hash=browser_context_hash,
                                    cursor_input=cursor,
                                    cursor_output=None,
                                    response_page_size=response_page_size,
                                    response_cursor_fields=(
                                        offertoday_listing_cursor_field_presence(
                                            response
                                        )
                                    ),
                                    previously_seen_job_ids=v2_seen_job_ids,
                                    awaiting_empty_confirmation=(
                                        awaiting_empty_confirmation
                                    ),
                                    contract_error=exc.reason,
                                ),
                            )
                            observations.append(observation)
                            await observation_sink.record_page_attempt(observation)
                            condition_stop_reason = violation_stop_reason
                            break
                        raw_rows = list(page_contract.result_rows)
                        raw_supplemental_rows = list(page_contract.supplemental_rows)
                        parsed_rows = parse_offertoday_listing_rows(raw_rows)
                        parsed_supplemental_rows = parse_offertoday_listing_rows(
                            raw_supplemental_rows
                        )
                        has_more = page_contract.has_more
                        reported_total = page_contract.reported_total
                        next_cursor = page_contract.cursor
                    else:
                        parsed_rows = parse_offertoday_listing_response(response)
                        parsed_supplemental_rows = []
                        raw_data = response.get("data")
                        if not isinstance(raw_data, Mapping):  # pragma: no cover
                            raise AssertionError(
                                "success listing response requires data"
                            )
                        raw_rows = raw_data.get("resultList")
                        if not isinstance(raw_rows, list):  # pragma: no cover
                            raise AssertionError(
                                "success listing response requires resultList"
                            )
                        raw_has_more = raw_data.get("hasMore")
                        has_more = (
                            raw_has_more if type(raw_has_more) is bool else None
                        )
                        raw_total = raw_data.get("total")
                        reported_total = (
                            raw_total if type(raw_total) is int else None
                        )
                    page_succeeded = True
                    pages_observed += 1

                    row_analyses = tuple(
                        _analyze_listing_row(row) for row in parsed_rows
                    )
                    supplemental_row_analyses = tuple(
                        _analyze_listing_row(row)
                        for row in parsed_supplemental_rows
                    )
                    row_evidence = tuple(analysis.evidence for analysis in row_analyses)
                    page_ordered_job_ids: list[str] = []
                    page_ordered_job_id_set: set[str] = set()
                    result_page_job_ids: set[str] = set()
                    page_issues: list[ListingIdentityIssue] = []
                    page_conflicts: list[ListingIdentityConflict] = []
                    supplemental_page_issues: list[ListingIdentityIssue] = []
                    supplemental_page_conflicts: list[ListingIdentityConflict] = []
                    page_conflict_keys: set[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = set()
                    page_deferrals: list[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = []
                    page_deferral_keys: set[
                        tuple[tuple[str, ...], tuple[str, ...], str]
                    ] = set()
                    candidate_job_to_identity = dict(job_to_identity)
                    page_identities_by_job: dict[
                        str, list[OfferTodayDetailIdentity]
                    ] = {}
                    candidate_accepted_job_ids = set(accepted_job_ids)
                    page_rejected_job_ids: set[str] = set()
                    supplemental_identities_by_job: dict[
                        str, list[OfferTodayDetailIdentity]
                    ] = {}

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
                        conflict = ListingIdentityConflict(
                            job_ids=tuple(sorted(conflict.job_ids)),
                            encrypted_job_ids=tuple(sorted(conflict.encrypted_job_ids)),
                            reason=conflict.reason,
                        )
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

                    for analysis in row_analyses:
                        evidence = analysis.evidence
                        job_id = evidence.job_id
                        if job_id is not None and job_id not in ordered_job_id_set:
                            ordered_job_id_set.add(job_id)
                            ordered_job_ids.append(job_id)
                        if (
                            job_id is not None
                            and job_id not in page_ordered_job_id_set
                        ):
                            page_ordered_job_id_set.add(job_id)
                            page_ordered_job_ids.append(job_id)
                            result_page_job_ids.add(job_id)

                        if analysis.issue is not None:
                            issue = analysis.issue
                            page_issues.append(issue)
                            identity_issues.append(issue)
                            if job_id is not None:
                                page_rejected_job_ids.add(job_id)
                                known_identity = job_to_identity.get(job_id)
                                if known_identity is not None:
                                    add_deferral(
                                        (job_id,),
                                        (known_identity.encrypted_job_id,),
                                        issue.reason,
                                    )
                            continue

                        identity = analysis.identity
                        if identity is None:  # pragma: no cover - resolver invariant
                            raise AssertionError(
                                "valid listing row requires resolved identity"
                            )
                        page_identities_by_job.setdefault(identity.job_id, []).append(
                            identity
                        )

                    for analysis in supplemental_row_analyses:
                        if analysis.issue is not None:
                            supplemental_page_issues.append(analysis.issue)
                            continue
                        identity = analysis.identity
                        if identity is None:  # pragma: no cover - resolver invariant
                            continue
                        supplemental_identities_by_job.setdefault(
                            identity.job_id, []
                        ).append(identity)

                    supplemental_conflicted_job_ids: set[str] = set()
                    supplemental_conflict_reason_by_job: dict[str, str] = {}
                    for job_id, identities in supplemental_identities_by_job.items():
                        route_ids = {
                            identity.encrypted_job_id for identity in identities
                        }
                        current_identity = candidate_job_to_identity.get(job_id)
                        if current_identity is not None:
                            route_ids.add(current_identity.encrypted_job_id)
                        route_ids.update(
                            identity.encrypted_job_id
                            for identity in page_identities_by_job.get(job_id, [])
                        )
                        if len(route_ids) > 1:
                            supplemental_conflicted_job_ids.add(job_id)
                            supplemental_conflict_reason_by_job[job_id] = (
                                "supplemental_job_id_to_multiple_encrypted_ids"
                            )

                    supplemental_route_to_jobs: dict[str, set[str]] = {}
                    for job_id, identities in supplemental_identities_by_job.items():
                        for identity in identities:
                            supplemental_route_to_jobs.setdefault(
                                identity.encrypted_job_id, set()
                            ).add(job_id)
                            if any(
                                result_job_id != job_id
                                and result_identity.encrypted_job_id
                                == identity.encrypted_job_id
                                for result_job_id in (
                                    candidate_job_to_identity.keys()
                                    | page_identities_by_job.keys()
                                )
                                for result_identity in (
                                    [candidate_job_to_identity[result_job_id]]
                                    if result_job_id in candidate_job_to_identity
                                    else []
                                )
                                + page_identities_by_job.get(result_job_id, [])
                            ):
                                supplemental_conflicted_job_ids.add(job_id)
                                supplemental_conflict_reason_by_job[job_id] = (
                                    "supplemental_one_encrypted_id_to_multiple_job_ids"
                                )
                    for encrypted_job_id, job_ids in supplemental_route_to_jobs.items():
                        if len(job_ids) > 1:
                            for job_id in job_ids:
                                supplemental_conflicted_job_ids.add(job_id)
                                supplemental_conflict_reason_by_job.setdefault(
                                    job_id,
                                    "supplemental_one_encrypted_id_to_multiple_job_ids",
                                )
                    for job_id in sorted(supplemental_conflicted_job_ids):
                        identities = supplemental_identities_by_job[job_id]
                        supplemental_page_conflicts.append(
                            ListingIdentityConflict(
                                job_ids=(job_id,),
                                encrypted_job_ids=tuple(
                                    sorted(
                                        {
                                            identity.encrypted_job_id
                                            for identity in identities
                                        }
                                    )
                                ),
                                reason=supplemental_conflict_reason_by_job[job_id],
                            )
                        )

                    valid_supplemental_job_ids = tuple(
                        job_id
                        for job_id in supplemental_identities_by_job
                        if job_id not in supplemental_conflicted_job_ids
                    )
                    for job_id in valid_supplemental_job_ids:
                        if job_id not in supplemental_job_id_set:
                            supplemental_job_id_set.add(job_id)
                            supplemental_job_ids.append(job_id)
                    supplemental_rows_observed += len(raw_supplemental_rows)
                    supplemental_identity_issue_count += (
                        len(supplemental_page_issues)
                        + len(supplemental_page_conflicts)
                    )

                    for job_id in page_ordered_job_ids:
                        page_identities = page_identities_by_job.get(job_id)
                        if not page_identities:
                            continue
                        current = candidate_job_to_identity.get(job_id)
                        authority_inputs = tuple(
                            ([current] if current is not None else [])
                            + page_identities
                        )
                        authority_index = build_offertoday_identity_authority_index(
                            authority_inputs
                        )
                        reason = authority_index.conflict_reason_by_job.get(job_id)
                        if reason is not None:
                            add_conflict(
                                ListingIdentityConflict(
                                    job_ids=(job_id,),
                                    encrypted_job_ids=authority_index.explicit_ids_by_job[
                                        job_id
                                    ],
                                    reason=reason,
                                )
                            )
                            page_rejected_job_ids.add(job_id)
                            continue
                        candidate_job_to_identity[job_id] = (
                            authority_index.authoritative_identity_by_job[job_id]
                        )
                        if (
                            job_id in result_page_job_ids
                            and job_id not in deferred_job_ids
                        ):
                            candidate_accepted_job_ids.add(job_id)

                    candidate_authority_index = (
                        build_offertoday_identity_authority_index(
                            tuple(candidate_job_to_identity.values())
                        )
                    )
                    for encrypted_job_id, job_ids in sorted(
                        candidate_authority_index.route_to_job_ids.items()
                    ):
                        if len(job_ids) > 1:
                            add_conflict(
                                ListingIdentityConflict(
                                    job_ids=job_ids,
                                    encrypted_job_ids=(encrypted_job_id,),
                                    reason="one_encrypted_id_to_multiple_job_ids",
                                )
                            )

                    for conflict in page_conflicts:
                        for conflicted_job_id in conflict.job_ids:
                            page_rejected_job_ids.add(conflicted_job_id)
                            candidate_accepted_job_ids.discard(conflicted_job_id)

                    page_pairs = [
                        OfferTodayIdentityPair(
                            job_id=identity.job_id,
                            encrypted_job_id=identity.encrypted_job_id,
                            encrypted_job_id_source=(
                                identity.encrypted_job_id_source
                            ),
                        )
                        for job_id in page_ordered_job_ids
                        if job_id not in page_rejected_job_ids
                        and (
                            identity := candidate_job_to_identity.get(job_id)
                        )
                        is not None
                    ]

                    stage_rows: list[dict[str, Any]] = []
                    stage_identity_values: list[
                        tuple[str, str, OfferTodayEncryptedJobIdSource]
                    ] = []
                    page_stage_identity_values: set[
                        tuple[str, str, OfferTodayEncryptedJobIdSource]
                    ] = set()
                    if not page_issues and not page_conflicts:
                        for parsed_row, analysis in zip(parsed_rows, row_analyses):
                            identity = analysis.identity
                            if identity is None:
                                continue
                            identity_key = (
                                identity.job_id,
                                identity.encrypted_job_id,
                                identity.encrypted_job_id_source,
                            )
                            if (
                                identity_key in staged_identity_values
                                or identity_key in page_stage_identity_values
                            ):
                                continue
                            page_stage_identity_values.add(identity_key)
                            stage_identity_values.append(identity_key)
                            stage_rows.append(parsed_row)

                    result_evidence_job_ids = tuple(
                        analysis.evidence.job_id
                        for analysis in row_analyses
                        if analysis.evidence.job_id is not None
                    )
                    supplemental_evidence_job_ids = tuple(
                        job_id for job_id in valid_supplemental_job_ids
                    )
                    result_identity_evidence = tuple(
                        OfferTodayListingIdentityEvidenceV2(
                            job_id=analysis.identity.job_id,
                            encrypted_job_id=analysis.identity.encrypted_job_id,
                            encrypted_job_id_source=(
                                analysis.identity.encrypted_job_id_source
                            ),
                        )
                        for analysis in row_analyses
                        if analysis.identity is not None
                    )
                    supplemental_identity_evidence = tuple(
                        OfferTodayListingIdentityEvidenceV2(
                            job_id=identity.job_id,
                            encrypted_job_id=identity.encrypted_job_id,
                            encrypted_job_id_source=identity.encrypted_job_id_source,
                        )
                        for job_id in valid_supplemental_job_ids
                        for identity in supplemental_identities_by_job[job_id][:1]
                    )
                    has_any_rows = bool(raw_rows or raw_supplemental_rows)
                    is_nonempty_confirmation = (
                        terminal_policy != RESULT_TERMINAL_POLICY_ID
                        and awaiting_empty_confirmation
                        and has_any_rows
                    )
                    terminal_contract_verified = (
                        active_endpoint_contract is None
                        or active_endpoint_contract.terminal_verified
                    )
                    terminal_signal = terminal_contract_verified and (
                        (
                            not raw_rows
                            if terminal_policy == RESULT_TERMINAL_POLICY_ID
                            else not has_any_rows
                        )
                        or has_more is False
                    )
                    result_cohort_exhaustion = False
                    if terminal_policy == RESULT_TERMINAL_POLICY_ID:
                        if raw_rows:
                            result_empty_confirmation_count = 0
                        else:
                            cursor_continues = next_cursor is not None and (
                                (
                                    cursor is None
                                    and page == 1
                                )
                                or (
                                    cursor is not None
                                    and next_cursor.session_id == cursor.session_id
                                    and next_cursor.cursor_hash != cursor.cursor_hash
                                )
                            )
                            result_empty_confirmation_count = (
                                result_empty_confirmation_count + 1
                                if cursor_continues
                                else 0
                            )
                        result_cohort_exhaustion = (
                            result_empty_confirmation_count
                            >= RESULT_TERMINAL_CONFIRMATION_PAGE_COUNT
                        )
                    natural_exhaustion = (
                        awaiting_empty_confirmation
                        and (
                            not raw_rows
                            if terminal_policy == RESULT_TERMINAL_POLICY_ID
                            else not has_any_rows
                        )
                    ) or (
                        not stop_policy.require_empty_confirmation and terminal_signal
                    )
                    page_contract_violation = (
                        active_request_policy is not None
                        and is_nonempty_confirmation
                    )

                    if page_conflicts:
                        attempt_stop_reason = "identity_conflict"
                        condition_stop_reason = "identity_conflict"
                    elif page_issues:
                        attempt_stop_reason = "identity_issue"
                        condition_stop_reason = "identity_issue"
                    elif page_contract_violation:
                        attempt_stop_reason = "cursor_contract_violation"
                        condition_stop_reason = "cursor_contract_violation"
                    elif (
                        stop_policy.unique_job_cap is not None
                        and len(candidate_accepted_job_ids)
                        >= stop_policy.unique_job_cap
                    ):
                        attempt_stop_reason = "target_cap"
                        condition_stop_reason = "target_cap"
                    elif result_cohort_exhaustion:
                        attempt_stop_reason = "result_cohort_exhaustion"
                        condition_stop_reason = "result_cohort_exhaustion"
                        condition_is_complete = True
                    elif natural_exhaustion:
                        attempt_stop_reason = "natural_exhaustion"
                        condition_stop_reason = "natural_exhaustion"
                        condition_is_complete = True
                    else:
                        if awaiting_empty_confirmation:
                            awaiting_empty_confirmation = False
                        if terminal_signal:
                            awaiting_empty_confirmation = True

                        if page >= stop_policy.max_pages_per_condition:
                            attempt_stop_reason = "page_cap"
                            condition_stop_reason = "page_cap"
                            condition_is_partial = (
                                stop_policy.page_cap_behavior
                                == "retain-and-continue"
                            )
                        else:
                            attempt_stop_reason = None

                    if page_conflicts:
                        observation_classification = "identity_conflict"
                    elif page_issues:
                        observation_classification = "identity_issue"
                    elif is_nonempty_confirmation:
                        observation_classification = "contract_anomaly"
                    else:
                        observation_classification = classification.kind.value

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
                        classification=observation_classification,
                        api_code=classification.code,
                        reported_total=reported_total,
                        has_more=has_more,
                        row_count=len(raw_rows),
                        missing_job_id_count=sum(
                            analysis.job_id_issue_reason == "missing_job_id"
                            for analysis in row_analyses
                        ),
                        missing_encrypted_job_id_count=sum(
                            analysis.encrypted_job_id_issue_reason
                            == "missing_encrypted_job_id"
                            for analysis in row_analyses
                        ),
                        job_id_fallback_count=sum(
                            analysis.identity is not None
                            and analysis.identity.encrypted_job_id_source
                            == "jobId_fallback"
                            for analysis in row_analyses
                        ),
                        id_pairs=tuple(page_pairs),
                        rows=row_evidence,
                        identity_issues=tuple(page_issues),
                        identity_conflicts=tuple(page_conflicts),
                        latency_ms=latency_ms,
                        session_mode=session_mode,
                        retry_reason=None,
                        stop_reason=attempt_stop_reason,
                        response_url=current_url,
                        supplemental_identity_issues=tuple(
                            supplemental_page_issues
                        ),
                        supplemental_identity_conflicts=tuple(
                            supplemental_page_conflicts
                        ),
                        cursor_evidence=(
                            _v2_page_evidence(
                                policy=active_request_policy,
                                condition=condition,
                                page=page,
                                attempt=attempt,
                                browser_context_hash=browser_context_hash,
                                cursor_input=cursor,
                                cursor_output=next_cursor,
                                response_page_size=(
                                    page_contract.response_page_size
                                    if page_contract is not None
                                    else None
                                ),
                                response_cursor_fields=(
                                    page_contract.cursor_field_presence
                                    if page_contract is not None
                                    else None
                                ),
                                result_job_ids=result_evidence_job_ids,
                                supplemental_job_ids=(
                                    supplemental_evidence_job_ids
                                ),
                                result_identity_pairs=result_identity_evidence,
                                supplemental_identity_pairs=(
                                    supplemental_identity_evidence
                                ),
                                result_row_count=len(raw_rows),
                                supplemental_row_count=len(
                                    raw_supplemental_rows
                                ),
                                previously_seen_job_ids=v2_seen_job_ids,
                                terminal_signal=terminal_signal,
                                awaiting_empty_confirmation=(
                                    awaiting_empty_confirmation
                                ),
                                contract_error=(
                                    "nonempty_confirmation"
                                    if page_contract_violation
                                    else None
                                ),
                            )
                            if active_request_policy is not None
                            else None
                        ),
                    )
                    observations.append(observation)
                    await observation_sink.record_page_attempt(observation)
                    for job_ids, encrypted_job_ids, reason in page_deferrals:
                        await staging_sink.defer_identity_conflict(
                            job_ids=job_ids,
                            encrypted_job_ids=encrypted_job_ids,
                            reason=reason,
                        )
                    if page_issues or page_conflicts or page_contract_violation:
                        deferred_job_ids.update(page_rejected_job_ids)
                        accepted_job_ids.difference_update(page_rejected_job_ids)
                    else:
                        if stage_rows:
                            if (
                                active_request_policy is not None
                                and stop_policy.page_cap_behavior == "reject"
                            ):
                                pending_v2_stage_pages.append((page, stage_rows))
                            else:
                                await staging_sink.stage_page(
                                    condition=condition,
                                    page=page,
                                    rows=stage_rows,
                                )
                        job_to_identity = candidate_job_to_identity
                        accepted_job_ids = candidate_accepted_job_ids
                        staged_identity_values.update(stage_identity_values)
                        if active_request_policy is not None:
                            v2_seen_job_ids.update(result_evidence_job_ids)
                            v2_seen_job_ids.update(supplemental_evidence_job_ids)
                            if active_request_policy.requires_cursor:
                                if next_cursor is None:  # pragma: no cover
                                    raise AssertionError(
                                        "cursor mode success requires cursor output"
                                    )
                                if initial_session_id is None:
                                    initial_session_id = next_cursor.session_id
                                if effective_page_size is None:
                                    effective_page_size = (
                                        next_cursor.effective_page_size
                                    )
                                cursor = next_cursor
                    break

                if restart_condition:
                    continue
                if condition_stop_reason is not None:
                    break
                if not page_succeeded:  # pragma: no cover - retry loop invariant
                    raise AssertionError("page loop ended without an outcome")
                page += 1
                page_delay = retry_policy.page_delay_seconds
                if retry_policy.page_delay_range_seconds is not None:
                    lower, upper = retry_policy.page_delay_range_seconds
                    page_delay = self._uniform(lower, upper)
                if page_delay > 0:
                    await self._sleep(page_delay)

            if (
                not condition_is_complete
                and not condition_is_partial
                and request_policy is not None
            ):
                removed_job_ids = ordered_job_ids[condition_ordered_job_count:]
                del ordered_job_ids[condition_ordered_job_count:]
                ordered_job_id_set.difference_update(removed_job_ids)
                accepted_job_ids = condition_accepted_job_ids
                job_to_identity = condition_job_to_identity
                staged_identity_values = condition_staged_identity_values

            if condition_is_complete and active_request_policy is not None:
                for staged_page, staged_rows in pending_v2_stage_pages:
                    await staging_sink.stage_page(
                        condition=condition,
                        page=staged_page,
                        rows=staged_rows,
                    )

            outcome = ListingConditionOutcome(
                condition=condition,
                pages_observed=pages_observed,
                stop_reason=condition_stop_reason or "condition_incomplete",
                is_complete=condition_is_complete,
                is_partial=condition_is_partial,
            )
            outcomes.append(outcome)
            await observation_sink.record_condition_outcome(outcome)
            if condition_is_partial:
                capped_condition_ids.append(condition.condition_id)
                continue
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
        is_partial = (
            len(outcomes) == len(conditions)
            and any(outcome.is_partial for outcome in outcomes)
            and all(
                outcome.is_complete or outcome.is_partial for outcome in outcomes
            )
            and not gaps
            and not identity_conflicts
            and not identity_issues
        )
        if is_complete:
            run_stop_reason = "natural_exhaustion"
        elif is_partial:
            run_stop_reason = "page_cap"

        return ListingRunResult(
            ordered_job_ids=tuple(ordered_job_ids),
            accepted_job_ids=tuple(
                job_id for job_id in ordered_job_ids if job_id in accepted_job_ids
            ),
            id_pairs=tuple(
                OfferTodayIdentityPair(
                    job_id=identity.job_id,
                    encrypted_job_id=identity.encrypted_job_id,
                    encrypted_job_id_source=identity.encrypted_job_id_source,
                )
                for job_id in ordered_job_ids
                if job_id in accepted_job_ids
                and (identity := job_to_identity.get(job_id)) is not None
            ),
            observations=tuple(observations),
            condition_outcomes=tuple(outcomes),
            identity_conflicts=tuple(identity_conflicts),
            identity_issues=tuple(identity_issues),
            gaps=tuple(gaps),
            stop_reason=run_stop_reason or "condition_incomplete",
            is_complete=is_complete,
            is_partial=is_partial,
            capped_condition_ids=tuple(capped_condition_ids),
            supplemental_rows_observed=supplemental_rows_observed,
            supplemental_job_ids=tuple(supplemental_job_ids),
            supplemental_identity_issue_count=(
                supplemental_identity_issue_count
            ),
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
        response_url: str | None = None,
        cursor_evidence: OfferTodayListingPageEvidenceV2 | None = None,
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
            job_id_fallback_count=0,
            id_pairs=(),
            rows=(),
            identity_issues=(),
            identity_conflicts=(),
            latency_ms=latency_ms,
            session_mode=session_mode,
            retry_reason=retry_reason,
            stop_reason=stop_reason,
            response_url=response_url,
            cursor_evidence=cursor_evidence,
        )
