from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.sources.offertoday.listing_contract import OfferTodayListingRequestPolicy
from app.sources.offertoday.listing_runner import (
    ListingRunResult,
    listing_observation_to_payload,
)


BAKEOFF_CATEGORY_IDS = (118000, 112000, 127000)
BAKEOFF_ENDPOINT = "search"
BAKEOFF_ENDPOINT_PATH = "/wapi/geek/recommend/search/list"
BAKEOFF_RCD_TYPE = None
BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION = 10
BAKEOFF_MAX_ATTEMPTS_PER_PAGE = 2
BAKEOFF_REQUIRE_EMPTY_CONFIRMATION = True
BAKEOFF_RETRY_DELAYS_SECONDS = (5.0,)
BAKEOFF_PAGE_DELAY_RANGE_SECONDS = (3.0, 5.0)
BAKEOFF_TERMINAL_POLICY = "cursor-terminal-empty-confirmation-v1"
BAKEOFF_SESSION_MODE = "fresh-headless"
BAKEOFF_DUPLICATE_ABSOLUTE_REDUCTION = 0.10
BAKEOFF_DUPLICATE_RELATIVE_REDUCTION = 0.20
BAKEOFF_MIN_JACCARD = 0.95


@dataclass(frozen=True, slots=True)
class PaginationBakeoffVariant:
    variant_id: str
    pagination_mode: str
    requested_page_size: int
    browser_lifecycle: str

    def request_policy(self, *, repeat_index: int) -> OfferTodayListingRequestPolicy:
        return OfferTodayListingRequestPolicy(
            protocol_version=2,
            pagination_mode=self.pagination_mode,
            requested_page_size=self.requested_page_size,
            browser_lifecycle=self.browser_lifecycle,
            variant_id=self.variant_id,
            repeat_index=repeat_index,
        )


BAKEOFF_VARIANTS = (
    PaginationBakeoffVariant(
        variant_id="stateless-current",
        pagination_mode="stateless-control",
        requested_page_size=50,
        browser_lifecycle="shared-variant-runtime",
    ),
    PaginationBakeoffVariant(
        variant_id="ui-cursor",
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="shared-variant-runtime",
    ),
    PaginationBakeoffVariant(
        variant_id="ui-cursor-50",
        pagination_mode="response-cursor",
        requested_page_size=50,
        browser_lifecycle="shared-variant-runtime",
    ),
    PaginationBakeoffVariant(
        variant_id="ui-cursor-restart",
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="restart-each-page",
    ),
    PaginationBakeoffVariant(
        variant_id="ui-cursor-same-browser",
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="condition-local-runtime",
    ),
)


def pagination_bakeoff_controls_payload() -> dict[str, Any]:
    return {
        "protocol_version": 2,
        "endpoint": BAKEOFF_ENDPOINT,
        "endpoint_path": BAKEOFF_ENDPOINT_PATH,
        "rcd_type": BAKEOFF_RCD_TYPE,
        "category_ids": list(BAKEOFF_CATEGORY_IDS),
        "max_logical_pages_per_condition": (
            BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION
        ),
        "max_attempts_per_page": BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
        "require_empty_confirmation": BAKEOFF_REQUIRE_EMPTY_CONFIRMATION,
        "retry_delays_seconds": list(BAKEOFF_RETRY_DELAYS_SECONDS),
        "page_delay_range_seconds": list(BAKEOFF_PAGE_DELAY_RANGE_SECONDS),
        "terminal_policy": BAKEOFF_TERMINAL_POLICY,
        "session_mode": BAKEOFF_SESSION_MODE,
        "variants": [
            {
                "variant_id": variant.variant_id,
                "pagination_mode": variant.pagination_mode,
                "requested_page_size": variant.requested_page_size,
                "browser_lifecycle": variant.browser_lifecycle,
            }
            for variant in BAKEOFF_VARIANTS
        ],
    }


def pagination_bakeoff_thresholds_payload() -> dict[str, float | int]:
    return {
        "duplicate_absolute_reduction": BAKEOFF_DUPLICATE_ABSOLUTE_REDUCTION,
        "duplicate_relative_reduction": BAKEOFF_DUPLICATE_RELATIVE_REDUCTION,
        "minimum_jaccard": BAKEOFF_MIN_JACCARD,
        "maximum_request_cost_multiplier": 2,
    }

_VARIANTS_BY_ID = {variant.variant_id: variant for variant in BAKEOFF_VARIANTS}
_BAKEOFF_HARD_STOP_REASONS = frozenset(
    {
        "auth_expired",
        "waf_challenge",
        "ip_blocked",
        "id_mismatch",
        "identity_conflict",
        "identity_issue",
        "unresolved_gap",
        "cursor_contract_violation",
    }
)
_UNEXPECTED_BAKEOFF_FAILURE_RE = re.compile(
    r"unexpected_pagination_bakeoff_error:[A-Za-z_][A-Za-z0-9_]{0,127}"
)


def pagination_bakeoff_unexpected_failure_reason(error: BaseException) -> str:
    error_type = type(error).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", error_type) is None:
        error_type = "Exception"
    return f"unexpected_pagination_bakeoff_error:{error_type}"


def _validate_bakeoff_failure_reason(
    failure_reason: str,
    *,
    last_stop_reason: Any,
) -> None:
    if failure_reason.startswith("hard_stop:"):
        stop_reason = failure_reason.removeprefix("hard_stop:")
        if (
            stop_reason not in _BAKEOFF_HARD_STOP_REASONS
            or last_stop_reason != stop_reason
        ):
            raise ValueError("hard-stop failure reason does not match execution")
        return
    if _UNEXPECTED_BAKEOFF_FAILURE_RE.fullmatch(failure_reason) is None:
        raise ValueError("pagination bake-off failure reason is invalid")


@dataclass(frozen=True, slots=True)
class PaginationBakeoffOrderEntry:
    category_id: int
    variant_id: str
    category_order: int


@dataclass(frozen=True, slots=True)
class PaginationConditionExecution:
    repeat_index: int
    variant_id: str
    category_id: int
    category_order: int
    result: ListingRunResult


@dataclass(frozen=True, slots=True)
class PaginationVariantMetrics:
    variant_id: str
    logical_pages: int
    physical_attempts: int
    result_rows: int
    supplemental_rows: int
    distinct_result_ids: tuple[str, ...]
    distinct_supplemental_ids: tuple[str, ...]
    distinct_all_ids: tuple[str, ...]
    duplicate_rows: int
    duplicate_rate: float
    zero_new_full_pages: int
    cursor_violations: int
    unresolved_gaps: int
    identity_issues: int
    identity_conflicts: int
    conservation_difference: int
    unclassified_failures: int
    latency_ms: int
    response_page_sizes: tuple[int, ...]
    reported_totals: tuple[int, ...]
    response_page_size_drift_conditions: int
    reported_total_drift_conditions: int
    unique_contribution_ids: tuple[str, ...] = ()

    @property
    def requests_per_distinct_id(self) -> float | None:
        if not self.distinct_all_ids:
            return None
        return self.physical_attempts / len(self.distinct_all_ids)

    @property
    def seconds_per_distinct_id(self) -> float | None:
        if not self.distinct_all_ids:
            return None
        return self.latency_ms / 1000 / len(self.distinct_all_ids)

    def to_payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "logical_pages": self.logical_pages,
            "physical_attempts": self.physical_attempts,
            "result_rows": self.result_rows,
            "supplemental_rows": self.supplemental_rows,
            "distinct_result_ids": list(self.distinct_result_ids),
            "distinct_supplemental_ids": list(self.distinct_supplemental_ids),
            "distinct_all_ids": list(self.distinct_all_ids),
            "duplicate_rows": self.duplicate_rows,
            "duplicate_rate": self.duplicate_rate,
            "zero_new_full_pages": self.zero_new_full_pages,
            "cursor_violations": self.cursor_violations,
            "unresolved_gaps": self.unresolved_gaps,
            "identity_issues": self.identity_issues,
            "identity_conflicts": self.identity_conflicts,
            "conservation_difference": self.conservation_difference,
            "unclassified_failures": self.unclassified_failures,
            "latency_ms": self.latency_ms,
            "response_page_sizes": list(self.response_page_sizes),
            "reported_totals": list(self.reported_totals),
            "response_page_size_drift_conditions": (
                self.response_page_size_drift_conditions
            ),
            "reported_total_drift_conditions": (
                self.reported_total_drift_conditions
            ),
            "unique_contribution_ids": list(self.unique_contribution_ids),
            "requests_per_distinct_id": self.requests_per_distinct_id,
            "seconds_per_distinct_id": self.seconds_per_distinct_id,
        }


@dataclass(frozen=True, slots=True)
class PaginationBakeoffRepeat:
    repeat_index: int
    order_seed: int
    order: tuple[PaginationBakeoffOrderEntry, ...]
    executions: tuple[PaginationConditionExecution, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.repeat_index) is not int or self.repeat_index not in (1, 2):
            raise ValueError("repeat_index must be 1 or 2")
        if type(self.order_seed) is not int:
            raise ValueError("order_seed must be an exact integer")
        frozen_order = build_bakeoff_order(
            repeat_index=self.repeat_index,
            order_seed=self.order_seed,
        )
        if self.order != frozen_order:
            raise ValueError("order does not match the frozen seed")
        expected = tuple(
            (entry.category_id, entry.variant_id, entry.category_order)
            for entry in self.order[: len(self.executions)]
        )
        actual = tuple(
            (item.category_id, item.variant_id, item.category_order)
            for item in self.executions
        )
        if expected != actual:
            raise ValueError("execution order does not match the frozen order")
        if self.failure_reason is None:
            if len(self.executions) != len(self.order):
                raise ValueError("completed repeat requires every frozen execution")
        elif (
            not isinstance(self.failure_reason, str)
            or not self.failure_reason
            or self.failure_reason != self.failure_reason.strip()
            or len(self.executions) > len(self.order)
        ):
            raise ValueError("failed repeat requires a bounded nonblank reason")
        else:
            _validate_bakeoff_failure_reason(
                self.failure_reason,
                last_stop_reason=(
                    self.executions[-1].result.stop_reason
                    if self.executions
                    else None
                ),
            )


@dataclass(frozen=True, slots=True)
class PaginationVariantComparison:
    variant_id: str
    accepted: bool
    rejection_reasons: tuple[str, ...]
    distinct_union_count: int
    logical_pages: int
    duplicate_rate: float
    duplicate_absolute_reduction: float
    duplicate_relative_reduction: float
    minimum_condition_jaccard: float
    minimum_same_page_jaccard: float
    unique_contribution_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "accepted": self.accepted,
            "rejection_reasons": list(self.rejection_reasons),
            "distinct_union_count": self.distinct_union_count,
            "logical_pages": self.logical_pages,
            "duplicate_rate": self.duplicate_rate,
            "duplicate_absolute_reduction": self.duplicate_absolute_reduction,
            "duplicate_relative_reduction": self.duplicate_relative_reduction,
            "minimum_condition_jaccard": self.minimum_condition_jaccard,
            "minimum_same_page_jaccard": self.minimum_same_page_jaccard,
            "unique_contribution_ids": list(self.unique_contribution_ids),
        }


@dataclass(frozen=True, slots=True)
class PaginationBakeoffDecision:
    accepted: bool
    selected_variant_id: str | None
    comparisons: tuple[PaginationVariantComparison, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "selected_variant_id": self.selected_variant_id,
            "comparisons": [item.to_payload() for item in self.comparisons],
        }


def build_bakeoff_order(
    *,
    repeat_index: int,
    order_seed: int,
) -> tuple[PaginationBakeoffOrderEntry, ...]:
    if type(repeat_index) is not int or repeat_index not in (1, 2):
        raise ValueError("repeat_index must be 1 or 2")
    if type(order_seed) is not int:
        raise ValueError("order_seed must be an exact integer")
    order: list[PaginationBakeoffOrderEntry] = []
    for category_id in BAKEOFF_CATEGORY_IDS:
        material = f"{order_seed}:{repeat_index}:{category_id}".encode()
        category_seed = int.from_bytes(hashlib.sha256(material).digest(), "big")
        variant_ids = [variant.variant_id for variant in BAKEOFF_VARIANTS]
        random.Random(category_seed).shuffle(variant_ids)
        order.extend(
            PaginationBakeoffOrderEntry(
                category_id=category_id,
                variant_id=variant_id,
                category_order=index,
            )
            for index, variant_id in enumerate(variant_ids, start=1)
        )
    return tuple(order)


def bakeoff_variant(variant_id: str) -> PaginationBakeoffVariant:
    try:
        return _VARIANTS_BY_ID[variant_id]
    except KeyError as exc:
        raise ValueError(f"unknown pagination bake-off variant: {variant_id}") from exc


def _ordered_distinct(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def summarize_variant(
    variant_id: str,
    executions: Sequence[PaginationConditionExecution],
) -> PaginationVariantMetrics:
    selected = tuple(item for item in executions if item.variant_id == variant_id)
    if not selected:
        raise ValueError(f"no executions for variant {variant_id}")
    observations = tuple(
        observation
        for execution in selected
        for observation in execution.result.observations
    )
    evidence = tuple(
        observation.cursor_evidence
        for observation in observations
        if observation.cursor_evidence is not None
    )
    if len(evidence) != len(observations):
        raise ValueError("pagination bake-off observations require v2 evidence")
    result_ids = _ordered_distinct(
        job_id for item in evidence for job_id in item.result_job_ids
    )
    supplemental_ids = _ordered_distinct(
        job_id for item in evidence for job_id in item.supplemental_job_ids
    )
    all_ids = _ordered_distinct((*result_ids, *supplemental_ids))
    result_rows = sum(item.result_row_count for item in evidence)
    supplemental_rows = sum(item.supplemental_row_count for item in evidence)
    raw_rows = result_rows + supplemental_rows
    observed_identity_rows = sum(
        len(item.result_job_ids) + len(item.supplemental_job_ids)
        for item in evidence
    )
    duplicate_rows = sum(item.duplicate_job_id_count for item in evidence)
    known_attempt_classifications = {
        "success",
        "transient_transport",
    }
    return PaginationVariantMetrics(
        variant_id=variant_id,
        logical_pages=len({item.logical_request_id for item in evidence}),
        physical_attempts=len(evidence),
        result_rows=result_rows,
        supplemental_rows=supplemental_rows,
        distinct_result_ids=result_ids,
        distinct_supplemental_ids=supplemental_ids,
        distinct_all_ids=all_ids,
        duplicate_rows=duplicate_rows,
        duplicate_rate=duplicate_rows / raw_rows if raw_rows else 0.0,
        zero_new_full_pages=sum(
            item.zero_new_full_page and item.condition_restart_index == 0
            for item in evidence
        ),
        cursor_violations=sum(
            observation.classification
            in {"cursor_contract_violation", "contract_anomaly"}
            for observation in observations
        ),
        unresolved_gaps=sum(
            len(item.result.gaps) + int(not item.result.is_complete)
            for item in selected
        ),
        identity_issues=sum(len(item.result.identity_issues) for item in selected),
        identity_conflicts=sum(
            len(item.result.identity_conflicts) for item in selected
        ),
        conservation_difference=raw_rows - observed_identity_rows,
        unclassified_failures=sum(
            observation.classification not in known_attempt_classifications
            for observation in observations
        ),
        latency_ms=sum(observation.latency_ms for observation in observations),
        response_page_sizes=tuple(
            item.response_page_size
            for item in evidence
            if item.response_page_size is not None
        ),
        reported_totals=tuple(
            observation.reported_total
            for observation in observations
            if observation.reported_total is not None
        ),
        response_page_size_drift_conditions=sum(
            len(
                {
                    observation.cursor_evidence.response_page_size
                    for observation in execution.result.observations
                    if observation.cursor_evidence is not None
                    and observation.cursor_evidence.response_page_size is not None
                }
            )
            > 1
            for execution in selected
        ),
        reported_total_drift_conditions=sum(
            len(
                {
                    observation.reported_total
                    for observation in execution.result.observations
                    if observation.reported_total is not None
                }
            )
            > 1
            for execution in selected
        ),
    )


def summarize_repeat(
    repeat: PaginationBakeoffRepeat,
) -> tuple[PaginationVariantMetrics, ...]:
    if repeat.failure_reason is not None:
        raise ValueError("failed repeat cannot be summarized as complete")
    return _summarize_available_variants(repeat)


def _summarize_available_variants(
    repeat: PaginationBakeoffRepeat,
) -> tuple[PaginationVariantMetrics, ...]:
    available_variants = tuple(
        variant
        for variant in BAKEOFF_VARIANTS
        if any(
            execution.variant_id == variant.variant_id
            for execution in repeat.executions
        )
    )
    base = tuple(
        summarize_variant(variant.variant_id, repeat.executions)
        for variant in available_variants
    )
    id_sets = {item.variant_id: set(item.distinct_all_ids) for item in base}
    return tuple(
        PaginationVariantMetrics(
            **{
                **{
                    field_name: getattr(item, field_name)
                    for field_name in item.__dataclass_fields__
                    if field_name != "unique_contribution_ids"
                },
                "unique_contribution_ids": tuple(
                    sorted(
                        id_sets[item.variant_id]
                        - set().union(
                            *(
                                values
                                for key, values in id_sets.items()
                                if key != item.variant_id
                            )
                        )
                    )
                ),
            }
        )
        for item in base
    )


def pagination_bakeoff_to_payload(
    repeat: PaginationBakeoffRepeat,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "controls": pagination_bakeoff_controls_payload(),
        "thresholds": pagination_bakeoff_thresholds_payload(),
        "status": "failed" if repeat.failure_reason is not None else "completed",
        "failure_reason": repeat.failure_reason,
        "repeat_index": repeat.repeat_index,
        "order_seed": repeat.order_seed,
        "order": [asdict(item) for item in repeat.order],
        "executions": [
            {
                "repeat_index": item.repeat_index,
                "variant_id": item.variant_id,
                "category_id": item.category_id,
                "category_order": item.category_order,
                "stop_reason": item.result.stop_reason,
                "is_complete": item.result.is_complete,
                "gap_count": len(item.result.gaps),
                "identity_issue_count": len(item.result.identity_issues),
                "identity_conflict_count": len(item.result.identity_conflicts),
                "observations": [
                    listing_observation_to_payload(observation)
                    for observation in item.result.observations
                ],
            }
            for item in repeat.executions
        ],
        "variant_summaries": [
            item.to_payload() for item in _summarize_available_variants(repeat)
        ],
    }


def _validated_recorded_repeat(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema_version",
        "controls",
        "thresholds",
        "status",
        "failure_reason",
        "repeat_index",
        "order_seed",
        "order",
        "executions",
        "variant_summaries",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise ValueError("pagination bake-off payload fields do not match")
    repeat_index = payload["repeat_index"]
    order_seed = payload["order_seed"]
    if payload["schema_version"] != 2:
        raise ValueError("pagination bake-off schema_version must equal 2")
    if payload["controls"] != pagination_bakeoff_controls_payload():
        raise ValueError("pagination bake-off controls do not match")
    if payload["thresholds"] != pagination_bakeoff_thresholds_payload():
        raise ValueError("pagination bake-off thresholds do not match")
    if payload["status"] not in {"completed", "failed"}:
        raise ValueError("pagination bake-off status is invalid")
    if payload["status"] == "completed":
        if payload["failure_reason"] is not None:
            raise ValueError("completed bake-off cannot have a failure reason")
    elif (
        not isinstance(payload["failure_reason"], str)
        or not payload["failure_reason"]
        or payload["failure_reason"] != payload["failure_reason"].strip()
    ):
        raise ValueError("failed bake-off requires a nonblank failure reason")
    expected_order = build_bakeoff_order(
        repeat_index=repeat_index,
        order_seed=order_seed,
    )
    raw_order = payload["order"]
    if not isinstance(raw_order, list) or raw_order != [
        asdict(item) for item in expected_order
    ]:
        raise ValueError("pagination bake-off order does not match frozen seed")
    executions = payload["executions"]
    if (
        not isinstance(executions, list)
        or len(executions) > len(expected_order)
        or (payload["status"] == "completed" and len(executions) != len(expected_order))
    ):
        raise ValueError("pagination bake-off execution count is invalid")
    expected_execution_keys = {
        "repeat_index",
        "variant_id",
        "category_id",
        "category_order",
        "stop_reason",
        "is_complete",
        "gap_count",
        "identity_issue_count",
        "identity_conflict_count",
        "observations",
    }
    for expected, execution in zip(expected_order, executions):
        if not isinstance(execution, dict) or set(execution) != expected_execution_keys:
            raise ValueError("pagination execution payload is invalid")
        if (
            execution["repeat_index"] != repeat_index
            or execution["variant_id"] != expected.variant_id
            or execution["category_id"] != expected.category_id
            or execution["category_order"] != expected.category_order
            or not isinstance(execution["observations"], list)
        ):
            raise ValueError("pagination execution does not match frozen order")
    if payload["status"] == "failed":
        _validate_bakeoff_failure_reason(
            payload["failure_reason"],
            last_stop_reason=(executions[-1]["stop_reason"] if executions else None),
        )
    summaries = payload["variant_summaries"]
    expected_summary_ids = [
        variant.variant_id
        for variant in BAKEOFF_VARIANTS
        if any(
            execution["variant_id"] == variant.variant_id
            for execution in executions
        )
    ]
    if (
        not isinstance(summaries, list)
        or [
            item.get("variant_id")
            for item in summaries
            if isinstance(item, dict)
        ]
        != expected_summary_ids
        or any(not isinstance(item, dict) for item in summaries)
    ):
        raise ValueError("pagination variant summaries are incomplete")
    summaries_by_id = {item["variant_id"]: item for item in summaries}
    return {
        "status": payload["status"],
        "repeat_index": repeat_index,
        "order_seed": order_seed,
        "executions": executions,
        "summaries": summaries_by_id,
    }


def validate_bakeoff_payload(payload: Mapping[str, Any]) -> None:
    _validated_recorded_repeat(payload)


def canonical_bakeoff_payload_hash(payload: Mapping[str, Any]) -> str:
    validate_bakeoff_payload(payload)
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _recorded_execution_ids(execution: Mapping[str, Any]) -> set[str]:
    return {
        str(job_id)
        for observation in execution["observations"]
        if isinstance(observation, Mapping)
        and isinstance(observation.get("cursor_evidence"), Mapping)
        for job_id in (
            *(observation["cursor_evidence"].get("result_job_ids") or []),
            *(observation["cursor_evidence"].get("supplemental_job_ids") or []),
        )
        if str(job_id)
    }


def _recorded_page_ids(execution: Mapping[str, Any]) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for observation in execution["observations"]:
        if (
            not isinstance(observation, Mapping)
            or observation.get("classification") != "success"
            or not isinstance(observation.get("cursor_evidence"), Mapping)
        ):
            continue
        page = observation.get("page")
        if type(page) is not int or page < 1:
            continue
        evidence = observation["cursor_evidence"]
        result[page] = {
            str(value)
            for value in (
                *(evidence.get("result_job_ids") or []),
                *(evidence.get("supplemental_job_ids") or []),
            )
            if str(value)
        }
    return result


def compare_bakeoff_payloads(
    first_payload: Mapping[str, Any],
    second_payload: Mapping[str, Any],
) -> PaginationBakeoffDecision:
    first = _validated_recorded_repeat(first_payload)
    second = _validated_recorded_repeat(second_payload)
    if first["status"] != "completed" or second["status"] != "completed":
        raise ValueError("comparison requires completed bake-off artifacts")
    if {first["repeat_index"], second["repeat_index"]} != {1, 2}:
        raise ValueError("comparison requires repeat indices 1 and 2")
    if first["order_seed"] != second["order_seed"]:
        raise ValueError("comparison requires one frozen order seed")
    by_repeat = {first["repeat_index"]: first, second["repeat_index"]: second}
    combined_ids = {
        variant.variant_id: set(
            by_repeat[1]["summaries"][variant.variant_id]["distinct_all_ids"]
        )
        | set(
            by_repeat[2]["summaries"][variant.variant_id]["distinct_all_ids"]
        )
        for variant in BAKEOFF_VARIANTS
    }
    control_summaries = (
        by_repeat[1]["summaries"]["stateless-current"],
        by_repeat[2]["summaries"]["stateless-current"],
    )
    control_rows = sum(
        item["result_rows"] + item["supplemental_rows"]
        for item in control_summaries
    )
    control_duplicates = sum(item["duplicate_rows"] for item in control_summaries)
    control_rate = control_duplicates / control_rows if control_rows else 0.0
    control_pages = sum(item["logical_pages"] for item in control_summaries)
    comparisons: list[PaginationVariantComparison] = []
    for variant in BAKEOFF_VARIANTS:
        if variant.variant_id == "stateless-current":
            continue
        summaries = (
            by_repeat[1]["summaries"][variant.variant_id],
            by_repeat[2]["summaries"][variant.variant_id],
        )
        rows = sum(
            item["result_rows"] + item["supplemental_rows"] for item in summaries
        )
        duplicate_rows = sum(item["duplicate_rows"] for item in summaries)
        duplicate_rate = duplicate_rows / rows if rows else 0.0
        absolute_reduction = control_rate - duplicate_rate
        relative_reduction = (
            absolute_reduction / control_rate if control_rate > 0 else 0.0
        )
        condition_jaccards: list[float] = []
        page_jaccards: list[float] = []
        for category_id in BAKEOFF_CATEGORY_IDS:
            repeat_executions = []
            for repeat_index in (1, 2):
                repeat_executions.append(
                    next(
                        item
                        for item in by_repeat[repeat_index]["executions"]
                        if item["variant_id"] == variant.variant_id
                        and item["category_id"] == category_id
                    )
                )
            condition_jaccards.append(
                _jaccard(
                    _recorded_execution_ids(repeat_executions[0]),
                    _recorded_execution_ids(repeat_executions[1]),
                )
            )
            first_pages = _recorded_page_ids(repeat_executions[0])
            second_pages = _recorded_page_ids(repeat_executions[1])
            page_jaccards.extend(
                _jaccard(first_pages[page], second_pages[page])
                for page in sorted(set(first_pages) & set(second_pages))
            )
        minimum_condition_jaccard = min(condition_jaccards, default=1.0)
        minimum_page_jaccard = min(page_jaccards, default=1.0)
        logical_pages = sum(item["logical_pages"] for item in summaries)
        reasons: list[str] = []
        for field_name, reason in (
            ("cursor_violations", "cursor_violation"),
            ("unresolved_gaps", "unresolved_gap"),
            ("identity_issues", "identity_issue"),
            ("identity_conflicts", "identity_conflict"),
            ("conservation_difference", "conservation_difference"),
            ("unclassified_failures", "unclassified_failure"),
            ("zero_new_full_pages", "unclassified_zero_new_full_page"),
        ):
            if any(item[field_name] for item in summaries):
                reasons.append(reason)
        if absolute_reduction < BAKEOFF_DUPLICATE_ABSOLUTE_REDUCTION:
            reasons.append("duplicate_absolute_reduction")
        if relative_reduction < BAKEOFF_DUPLICATE_RELATIVE_REDUCTION:
            reasons.append("duplicate_relative_reduction")
        if len(combined_ids[variant.variant_id]) < len(
            combined_ids["stateless-current"]
        ):
            reasons.append("distinct_union_below_control")
        if logical_pages > 2 * control_pages:
            reasons.append("request_cost_above_2x")
        if minimum_condition_jaccard < BAKEOFF_MIN_JACCARD:
            reasons.append("condition_jaccard")
        unique_contribution = combined_ids[variant.variant_id] - set().union(
            *(
                values
                for key, values in combined_ids.items()
                if key != variant.variant_id
            )
        )
        comparisons.append(
            PaginationVariantComparison(
                variant_id=variant.variant_id,
                accepted=not reasons,
                rejection_reasons=tuple(reasons),
                distinct_union_count=len(combined_ids[variant.variant_id]),
                logical_pages=logical_pages,
                duplicate_rate=duplicate_rate,
                duplicate_absolute_reduction=absolute_reduction,
                duplicate_relative_reduction=relative_reduction,
                minimum_condition_jaccard=minimum_condition_jaccard,
                minimum_same_page_jaccard=minimum_page_jaccard,
                unique_contribution_ids=tuple(sorted(unique_contribution)),
            )
        )
    accepted = [item for item in comparisons if item.accepted]
    selected = accepted[0] if len(accepted) == 1 else None
    return PaginationBakeoffDecision(
        accepted=selected is not None,
        selected_variant_id=selected.variant_id if selected is not None else None,
        comparisons=tuple(comparisons),
    )


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def compare_bakeoff_repeats(
    first: PaginationBakeoffRepeat,
    second: PaginationBakeoffRepeat,
) -> PaginationBakeoffDecision:
    return compare_bakeoff_payloads(
        pagination_bakeoff_to_payload(first),
        pagination_bakeoff_to_payload(second),
    )
