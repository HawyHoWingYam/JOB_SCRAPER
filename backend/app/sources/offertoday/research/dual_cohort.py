"""Pure additive contracts for OfferToday result and supplemental cohorts.

Historical Phase C/D payloads deliberately keep their envelope-wide terminal
semantics.  This module adds a separate, strictly versioned boundary that
replays result-partition exhaustion and supplemental stability without
changing any v1/v2 class, experiment name, or canonical hash.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.listing_runner import (
    ENVELOPE_TERMINAL_POLICY_ID,
    RESULT_TERMINAL_CONFIRMATION_PAGE_COUNT,
    RESULT_TERMINAL_POLICY_ID,
)
from app.sources.offertoday.research.partition_research import (
    OFFERTODAY_PARTITION_CATALOG,
    phase_c_request_policy_hash,
    offertoday_partition,
    offertoday_partition_catalog_hash,
    top_level_partition,
)
from app.sources.offertoday.research.phase_d import (
    PhaseDConditionEvidence,
    PhaseDPageAttempt,
    PhaseDProductEvidence,
    phase_d_id_set_hash,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCBaselineReference,
)


RESULT_PARTITION_PROBE_EXPERIMENT = "result-partition-probe-v2"
RESULT_PARTITION_POLICY_EXPERIMENT = "result-partition-policy-v1"
SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT = "supplemental-cohort-probe-v1"
SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT = (
    "supplemental-cohort-stability-comparison-v1"
)
DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT = (
    "dual-cohort-discovery-policy-candidate-v3"
)
RESULT_PARTIAL_CENSUS_EXPERIMENT = "cursor-result-partial-census-v3"
RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT = (
    "cursor-result-partial-fixed-repeat-v3"
)
DUAL_COHORT_CENSUS_EXPERIMENT = "cursor-dual-cohort-full-census-v3"
DUAL_COHORT_FIXED_REPEAT_EXPERIMENT = (
    "cursor-dual-cohort-fixed-repeat-v3"
)
DUAL_COHORT_COMPARISON_EXPERIMENT = (
    "cursor-dual-cohort-stability-comparison-v3"
)

RESULT_ADMISSION_POLICY_ID = "result-list-only-v1"
RESULT_CONFIRMATION_PAGE_COUNT = RESULT_TERMINAL_CONFIRMATION_PAGE_COUNT
DUAL_COHORT_REQUESTED_PAGE_SIZE = 10
DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE = 3
RESULT_PROBE_MAX_PAGES_PER_CONDITION = 10
SUPPLEMENTAL_MAX_PAGES_PER_SEED = 10
SUPPLEMENTAL_MIN_JACCARD = 0.95
SUPPLEMENTAL_MIN_CONTRIBUTION_RATIO = 0.005
SUPPLEMENTAL_SEED_CATEGORY_IDS = (112000, 118000, 127000)
SUPPLEMENTAL_SEED_PARTITION_IDS = tuple(
    top_level_partition(category_id).partition_id
    for category_id in SUPPLEMENTAL_SEED_CATEGORY_IDS
)
DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION = 500
DUAL_COHORT_PHASE_D_RETRY_DELAYS_SECONDS = (5.0, 15.0)
DUAL_COHORT_PHASE_D_PAGE_DELAY_RANGE_SECONDS = (3.0, 5.0)
DUAL_COHORT_PHASE_D_SESSION_MODE = "saved-session"
DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS = (118000, 112000, 127000)
DUAL_COHORT_DEFERRED_ISSUE_IDS = (4, 5)
DUAL_COHORT_CENSUS_MIN_WINDOW_SECONDS = 21_600.0
DUAL_COHORT_FIXED_MAX_WINDOW_SECONDS = 3_600.0

_SHA256_LENGTH = 64
_PARTITION_ORDER = {
    partition.partition_id: index
    for index, partition in enumerate(OFFERTODAY_PARTITION_CATALOG)
}


def canonical_dual_cohort_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _nonblank(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(
            f"{field_name} must be an exact integer >= {minimum}"
        )
    return value


def _finite_ratio(value: Any, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError(f"{field_name} must be a finite ratio in 0..1")
    return float(value)


def _finite_nonnegative(value: Any, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a finite nonnegative number")
    return float(value)


def _canonical_ids(values: Iterable[str]) -> tuple[str, ...]:
    items = tuple(values)
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in items
    ):
        raise ValueError("job IDs must be nonblank trimmed strings")
    return tuple(sorted(set(items)))


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(value)
    if any(
        not isinstance(item, str)
        or not item
        or item != item.strip()
        for item in result
    ):
        raise ValueError(f"{field_name} must contain nonblank trimmed strings")
    return result


def _canonical_uuid(value: Any, field_name: str) -> str:
    _nonblank(value, field_name)
    try:
        canonical = str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a canonical UUID") from exc
    if value != canonical:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return canonical


def _aware_datetime(value: Any, field_name: str) -> datetime:
    _nonblank(value, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _minimum_pairwise_jaccard(cohorts: Sequence[Iterable[str]]) -> float:
    values = tuple(tuple(cohort) for cohort in cohorts)
    if len(values) < 2:
        return 1.0
    return min(_jaccard(left, right) for left, right in combinations(values, 2))


def _successful_page_attempts(
    pages: Sequence[PhaseDPageAttempt],
) -> tuple[PhaseDPageAttempt, ...]:
    return tuple(page for page in pages if page.classification == "success")


@dataclass(frozen=True, slots=True)
class ResultCohortTerminalDecisionV1:
    final_restart_index: int
    successful_page_numbers: tuple[int, ...]
    confirmation_logical_request_ids: tuple[str, ...]
    result_job_ids: tuple[str, ...]
    supplemental_job_ids: tuple[str, ...]
    cohort_overlap_job_ids: tuple[str, ...]
    cursor_continuity_verified: bool
    result_exhausted: bool
    failing_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        _exact_int(self.final_restart_index, "final_restart_index")
        if any(type(page) is not int or page < 1 for page in self.successful_page_numbers):
            raise ValueError("successful_page_numbers must contain positive integers")
        if tuple(sorted(set(self.successful_page_numbers))) != (
            self.successful_page_numbers
        ):
            raise ValueError("successful_page_numbers must be distinct and ordered")
        for value in self.confirmation_logical_request_ids:
            _sha256(value, "confirmation_logical_request_id")
        for field_name in (
            "result_job_ids",
            "supplemental_job_ids",
            "cohort_overlap_job_ids",
        ):
            values = getattr(self, field_name)
            if values != _canonical_ids(values):
                raise ValueError(f"{field_name} must be canonical")
        if self.cohort_overlap_job_ids != tuple(
            sorted(set(self.result_job_ids) & set(self.supplemental_job_ids))
        ):
            raise ValueError("cohort overlap does not match result/supplemental IDs")
        if type(self.cursor_continuity_verified) is not bool:
            raise ValueError("cursor_continuity_verified must be an exact boolean")
        if type(self.result_exhausted) is not bool:
            raise ValueError("result_exhausted must be an exact boolean")
        if any(not isinstance(gate, str) or not gate for gate in self.failing_gates):
            raise ValueError("failing_gates must contain nonblank strings")
        if self.result_exhausted != (not self.failing_gates):
            raise ValueError("result_exhausted does not match failing gates")
        if self.result_exhausted and len(self.confirmation_logical_request_ids) != (
            RESULT_CONFIRMATION_PAGE_COUNT
        ):
            raise ValueError("accepted result terminal needs two confirmation pages")

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_id": RESULT_TERMINAL_POLICY_ID,
            "final_restart_index": self.final_restart_index,
            "successful_page_numbers": list(self.successful_page_numbers),
            "confirmation_logical_request_ids": list(
                self.confirmation_logical_request_ids
            ),
            "result_job_ids": list(self.result_job_ids),
            "result_set_hash": phase_d_id_set_hash(self.result_job_ids),
            "supplemental_job_ids": list(self.supplemental_job_ids),
            "supplemental_set_hash": phase_d_id_set_hash(
                self.supplemental_job_ids
            ),
            "cohort_overlap_job_ids": list(self.cohort_overlap_job_ids),
            "cohort_overlap_hash": phase_d_id_set_hash(
                self.cohort_overlap_job_ids
            ),
            "cursor_continuity_verified": self.cursor_continuity_verified,
            "result_exhausted": self.result_exhausted,
            "failing_gates": list(self.failing_gates),
        }


def evaluate_result_cohort_terminal(
    pages: Sequence[PhaseDPageAttempt],
) -> ResultCohortTerminalDecisionV1:
    """Replay result exhaustion without reading total, page cap, or saturation."""

    page_items = tuple(pages)
    successful = _successful_page_attempts(page_items)
    all_result_ids = _canonical_ids(
        job_id
        for page in successful
        for job_id in page.cursor_evidence.result_job_ids
    )
    all_supplemental_ids = _canonical_ids(
        job_id
        for page in successful
        for job_id in page.cursor_evidence.supplemental_job_ids
    )
    final_restart_index = max(
        (
            page.cursor_evidence.condition_restart_index
            for page in page_items
        ),
        default=0,
    )
    final_successful = tuple(
        sorted(
            (
                page
                for page in successful
                if page.cursor_evidence.condition_restart_index
                == final_restart_index
            ),
            key=lambda page: (page.page, page.attempt),
        )
    )

    failing_gates: list[str] = []
    if not final_successful:
        failing_gates.append("successful_final_restart_chain")

    successful_page_numbers = tuple(page.page for page in final_successful)
    if final_successful:
        expected_pages = tuple(range(1, max(successful_page_numbers) + 1))
        if successful_page_numbers != expected_pages:
            failing_gates.append("contiguous_final_restart_pages")

    cursor_continuity = bool(final_successful)
    previous = None
    for index, page in enumerate(final_successful):
        evidence = page.cursor_evidence
        current_valid = (
            evidence.cursor_fields_complete
            and evidence.contract_error is None
            and evidence.cursor_output_hash is not None
            and evidence.session_output_hash is not None
        )
        if index == 0:
            current_valid = current_valid and (
                evidence.cursor_input_hash is None
                and evidence.session_input_hash is None
                and evidence.session_continuity == "initial"
            )
        else:
            previous_evidence = previous.cursor_evidence
            current_valid = current_valid and (
                evidence.cursor_input_hash
                == previous_evidence.cursor_output_hash
                and evidence.session_input_hash
                == previous_evidence.session_output_hash
                and evidence.session_output_hash
                == previous_evidence.session_output_hash
                and evidence.session_continuity == "continued"
                and evidence.cursor_input_hash != evidence.cursor_output_hash
            )
        cursor_continuity = cursor_continuity and current_valid
        previous = page
    if not cursor_continuity:
        failing_gates.append("cursor_continuity")

    last_result_index = max(
        (
            index
            for index, page in enumerate(final_successful)
            if page.cursor_evidence.result_job_ids
        ),
        default=-1,
    )
    trailing = final_successful[last_result_index + 1 :]
    confirmations = tuple(
        page
        for page in trailing[:RESULT_CONFIRMATION_PAGE_COUNT]
        if not page.cursor_evidence.result_job_ids
    )
    if (
        len(trailing) < RESULT_CONFIRMATION_PAGE_COUNT
        or len(confirmations) != RESULT_CONFIRMATION_PAGE_COUNT
    ):
        failing_gates.append("two_result_empty_confirmation_pages")

    confirmation_ids = tuple(
        page.cursor_evidence.logical_request_id for page in confirmations
    )
    failing_tuple = tuple(dict.fromkeys(failing_gates))
    return ResultCohortTerminalDecisionV1(
        final_restart_index=final_restart_index,
        successful_page_numbers=successful_page_numbers,
        confirmation_logical_request_ids=confirmation_ids,
        result_job_ids=all_result_ids,
        supplemental_job_ids=all_supplemental_ids,
        cohort_overlap_job_ids=tuple(
            sorted(set(all_result_ids) & set(all_supplemental_ids))
        ),
        cursor_continuity_verified=cursor_continuity,
        result_exhausted=not failing_tuple,
        failing_gates=failing_tuple,
    )


@dataclass(frozen=True, slots=True)
class ResultPartitionConditionEvidenceV2:
    condition: PhaseDConditionEvidence
    terminal: ResultCohortTerminalDecisionV1

    def __post_init__(self) -> None:
        replayed = evaluate_result_cohort_terminal(self.condition.pages)
        if self.terminal != replayed:
            raise ValueError("result terminal decision does not replay from pages")

    @classmethod
    def from_condition(
        cls,
        condition: PhaseDConditionEvidence,
    ) -> "ResultPartitionConditionEvidenceV2":
        return cls(
            condition=condition,
            terminal=evaluate_result_cohort_terminal(condition.pages),
        )

    @property
    def accepted(self) -> bool:
        condition = self.condition
        return (
            condition.is_complete
            and condition.stop_reason == "result_cohort_exhaustion"
            and self.terminal.result_exhausted
            and condition.gap_count == 0
            and condition.identity_conflict_count == 0
            and condition.identity_issue_count == 0
            and condition.conservation_difference == 0
            and condition.unexplained_rollover_count == 0
            and condition.cursor_contract_error_count == 0
            and condition.unclassified_failure_count == 0
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "condition": self.condition.to_payload(),
            "terminal": self.terminal.to_payload(),
            "result_job_ids": list(self.terminal.result_job_ids),
            "supplemental_job_ids": list(self.terminal.supplemental_job_ids),
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultPartitionConditionEvidenceV2":
        expected = {
            "condition",
            "terminal",
            "result_job_ids",
            "supplemental_job_ids",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("result partition condition fields do not match")
        condition = PhaseDConditionEvidence.from_payload(payload["condition"])
        value = cls.from_condition(condition)
        if dict(payload) != value.to_payload():
            raise ValueError("result partition condition does not replay")
        return value


@dataclass(frozen=True, slots=True)
class ResultPartitionProbePlanV2:
    endpoint_contract_id: str
    partition_ids: tuple[str, ...]
    max_pages_per_condition: int = RESULT_PROBE_MAX_PAGES_PER_CONDITION
    max_attempts_per_page: int = DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE
    requested_page_size: int = DUAL_COHORT_REQUESTED_PAGE_SIZE

    def __post_init__(self) -> None:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if not contract.cursor_verified or not contract.terminal_verified:
            raise ValueError("result probe requires a verified cursor endpoint")
        if contract.allowed_rcd_types != (None,):
            raise ValueError("result probe requires omitted rcdType")
        if (
            not isinstance(self.partition_ids, tuple)
            or not self.partition_ids
            or len(self.partition_ids) > 31
            or len(set(self.partition_ids)) != len(self.partition_ids)
        ):
            raise ValueError("result probe requires 1..31 distinct partitions")
        for partition_id in self.partition_ids:
            offertoday_partition(partition_id)
        if self.partition_ids != tuple(
            sorted(self.partition_ids, key=_PARTITION_ORDER.__getitem__)
        ):
            raise ValueError("result probe partitions must use catalog order")
        if self.max_pages_per_condition != RESULT_PROBE_MAX_PAGES_PER_CONDITION:
            raise ValueError("result probe page budget must equal the frozen value")
        if self.max_attempts_per_page != DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE:
            raise ValueError("result probe attempt budget must equal the frozen value")
        if self.requested_page_size != DUAL_COHORT_REQUESTED_PAGE_SIZE:
            raise ValueError("result probe page size must equal the frozen value")

    @property
    def plan_hash(self) -> str:
        return canonical_dual_cohort_hash(self.to_payload())

    @property
    def listing_logical_budget(self) -> int:
        return len(self.partition_ids) * self.max_pages_per_condition

    @property
    def listing_attempt_budget(self) -> int:
        return self.listing_logical_budget * self.max_attempts_per_page

    def to_payload(self) -> dict[str, Any]:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        return {
            "schema_version": 1,
            "endpoint_contract_id": contract.contract_id,
            "endpoint_contract_hash": contract.contract_hash,
            "partition_catalog_hash": offertoday_partition_catalog_hash(),
            "partition_ids": list(self.partition_ids),
            "partitions": [
                offertoday_partition(partition_id).to_payload()
                for partition_id in self.partition_ids
            ],
            "result_admission_policy": RESULT_ADMISSION_POLICY_ID,
            "terminal_policy": RESULT_TERMINAL_POLICY_ID,
            "confirmation_page_count": RESULT_CONFIRMATION_PAGE_COUNT,
            "request_policy_hash": phase_c_request_policy_hash(
                self.endpoint_contract_id
            ),
            "max_pages_per_condition": self.max_pages_per_condition,
            "max_attempts_per_page": self.max_attempts_per_page,
            "requested_page_size": self.requested_page_size,
            "listing_logical_budget": self.listing_logical_budget,
            "listing_attempt_budget": self.listing_attempt_budget,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultPartitionProbePlanV2":
        if not isinstance(payload, Mapping):
            raise ValueError("result probe plan must be a mapping")
        value = cls(
            endpoint_contract_id=payload.get("endpoint_contract_id"),
            partition_ids=_string_tuple(payload.get("partition_ids"), "partition_ids"),
            max_pages_per_condition=payload.get("max_pages_per_condition"),
            max_attempts_per_page=payload.get("max_attempts_per_page"),
            requested_page_size=payload.get("requested_page_size"),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("result probe plan does not replay")
        return value


@dataclass(frozen=True, slots=True)
class ResultPartitionProbeExecutionV2:
    plan: ResultPartitionProbePlanV2
    conditions: tuple[ResultPartitionConditionEvidenceV2, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        actual = tuple(item.condition.partition_id for item in self.conditions)
        if actual != self.plan.partition_ids[: len(actual)]:
            raise ValueError("result probe condition order does not match the plan")
        if self.failure_reason is None and actual != self.plan.partition_ids:
            raise ValueError("completed result probe requires every condition")
        if self.logical_requests > self.plan.listing_logical_budget:
            raise ValueError("result probe logical request budget exceeded")
        if self.physical_attempts > self.plan.listing_attempt_budget:
            raise ValueError("result probe physical attempt budget exceeded")

    @property
    def logical_requests(self) -> int:
        return sum(item.condition.logical_requests for item in self.conditions)

    @property
    def physical_attempts(self) -> int:
        return sum(item.condition.physical_attempts for item in self.conditions)

    @property
    def accepted(self) -> bool:
        return (
            self.failure_reason is None
            and bool(self.conditions)
            and all(item.accepted for item in self.conditions)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment": RESULT_PARTITION_PROBE_EXPERIMENT,
            "plan": self.plan.to_payload(),
            "plan_hash": self.plan.plan_hash,
            "conditions": [item.to_payload() for item in self.conditions],
            "failure_reason": self.failure_reason,
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultPartitionProbeExecutionV2":
        expected = {
            "schema_version",
            "experiment",
            "plan",
            "plan_hash",
            "conditions",
            "failure_reason",
            "logical_requests",
            "physical_attempts",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("result probe execution fields do not match")
        if (
            payload["schema_version"] != 1
            or payload["experiment"] != RESULT_PARTITION_PROBE_EXPERIMENT
            or not isinstance(payload["conditions"], list)
        ):
            raise ValueError("result probe execution contract does not match")
        value = cls(
            plan=ResultPartitionProbePlanV2.from_payload(payload["plan"]),
            conditions=tuple(
                ResultPartitionConditionEvidenceV2.from_payload(item)
                for item in payload["conditions"]
            ),
            failure_reason=payload["failure_reason"],
        )
        if dict(payload) != value.to_payload():
            raise ValueError("result probe execution does not replay")
        return value


@dataclass(frozen=True, slots=True)
class ResultPartitionPolicyV1:
    endpoint_contract_id: str
    endpoint_contract_hash: str
    partition_catalog_hash: str
    source_probe_artifact_hash: str
    source_condition_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("result policy endpoint hash does not match")
        if self.partition_catalog_hash != offertoday_partition_catalog_hash():
            raise ValueError("result policy partition catalog hash does not match")
        _sha256(self.source_probe_artifact_hash, "source_probe_artifact_hash")
        if not self.source_condition_hashes:
            raise ValueError("result policy requires source conditions")
        for value in self.source_condition_hashes:
            _sha256(value, "source_condition_hash")

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "policy_version": 1,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract_hash": self.endpoint_contract_hash,
            "partition_catalog_hash": self.partition_catalog_hash,
            "result_admission_policy": RESULT_ADMISSION_POLICY_ID,
            "terminal_policy": RESULT_TERMINAL_POLICY_ID,
            "confirmation_page_count": RESULT_CONFIRMATION_PAGE_COUNT,
            "request_policy_hash": phase_c_request_policy_hash(
                self.endpoint_contract_id
            ),
            "source_probe_artifact_hash": self.source_probe_artifact_hash,
            "source_condition_hashes": list(self.source_condition_hashes),
        }

    @property
    def policy_hash(self) -> str:
        return canonical_dual_cohort_hash(self._canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "policy_hash": self.policy_hash}

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultPartitionPolicyV1":
        expected = {
            "policy_version",
            "endpoint_contract_id",
            "endpoint_contract_hash",
            "partition_catalog_hash",
            "result_admission_policy",
            "terminal_policy",
            "confirmation_page_count",
            "request_policy_hash",
            "source_probe_artifact_hash",
            "source_condition_hashes",
            "policy_hash",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("result partition policy fields do not match")
        if (
            payload["policy_version"] != 1
            or payload["result_admission_policy"] != RESULT_ADMISSION_POLICY_ID
            or payload["terminal_policy"] != RESULT_TERMINAL_POLICY_ID
            or payload["confirmation_page_count"]
            != RESULT_CONFIRMATION_PAGE_COUNT
        ):
            raise ValueError("result partition policy contract does not match")
        value = cls(
            endpoint_contract_id=payload["endpoint_contract_id"],
            endpoint_contract_hash=payload["endpoint_contract_hash"],
            partition_catalog_hash=payload["partition_catalog_hash"],
            source_probe_artifact_hash=payload["source_probe_artifact_hash"],
            source_condition_hashes=_string_tuple(
                payload["source_condition_hashes"],
                "source_condition_hashes",
            ),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("result partition policy does not replay")
        return value


def freeze_result_partition_policy_v1(
    execution: ResultPartitionProbeExecutionV2,
    *,
    source_probe_artifact_hash: str,
) -> ResultPartitionPolicyV1:
    if not execution.accepted:
        raise ValueError("result partition policy requires an accepted probe")
    contract = offertoday_endpoint_contract(execution.plan.endpoint_contract_id)
    return ResultPartitionPolicyV1(
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        partition_catalog_hash=offertoday_partition_catalog_hash(),
        source_probe_artifact_hash=source_probe_artifact_hash,
        source_condition_hashes=tuple(
            canonical_dual_cohort_hash(item.to_payload())
            for item in execution.conditions
        ),
    )


def result_partition_policy_artifact_payload_v1(
    policy: ResultPartitionPolicyV1,
) -> dict[str, Any]:
    policy_payload = policy.to_payload()
    return {
        "schema_version": 1,
        "experiment": RESULT_PARTITION_POLICY_EXPERIMENT,
        "policy": policy_payload,
        "policy_hash": policy.policy_hash,
        "source_probe_artifact_hash": policy.source_probe_artifact_hash,
        "policy_frozen": True,
    }


def validate_result_partition_policy_artifact_payload_v1(
    payload: Any,
) -> ResultPartitionPolicyV1:
    expected = {
        "schema_version",
        "experiment",
        "policy",
        "policy_hash",
        "source_probe_artifact_hash",
        "policy_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("result partition policy artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != RESULT_PARTITION_POLICY_EXPERIMENT
        or payload["policy_frozen"] is not True
    ):
        raise ValueError("result partition policy artifact contract does not match")
    policy = ResultPartitionPolicyV1.from_payload(payload["policy"])
    expected_payload = result_partition_policy_artifact_payload_v1(policy)
    if dict(payload) != expected_payload:
        raise ValueError("result partition policy artifact does not replay")
    return policy


@dataclass(frozen=True, slots=True)
class SupplementalCohortProbePlanV1:
    endpoint_contract_id: str
    seed_partition_ids: tuple[str, ...] = SUPPLEMENTAL_SEED_PARTITION_IDS
    max_pages_per_seed: int = SUPPLEMENTAL_MAX_PAGES_PER_SEED
    max_attempts_per_page: int = DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE
    requested_page_size: int = DUAL_COHORT_REQUESTED_PAGE_SIZE

    def __post_init__(self) -> None:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if not contract.cursor_verified or not contract.terminal_verified:
            raise ValueError("supplemental probe requires a verified endpoint")
        if self.seed_partition_ids != SUPPLEMENTAL_SEED_PARTITION_IDS:
            raise ValueError("supplemental seeds must equal the frozen catalog set")
        if self.max_pages_per_seed != SUPPLEMENTAL_MAX_PAGES_PER_SEED:
            raise ValueError("supplemental page budget must equal the frozen value")
        if self.max_attempts_per_page != DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE:
            raise ValueError("supplemental attempt budget must equal the frozen value")
        if self.requested_page_size != DUAL_COHORT_REQUESTED_PAGE_SIZE:
            raise ValueError("supplemental page size must equal the frozen value")

    @property
    def plan_hash(self) -> str:
        return canonical_dual_cohort_hash(self.to_payload())

    @property
    def listing_logical_budget(self) -> int:
        return len(self.seed_partition_ids) * self.max_pages_per_seed

    @property
    def listing_attempt_budget(self) -> int:
        return self.listing_logical_budget * self.max_attempts_per_page

    def to_payload(self) -> dict[str, Any]:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        return {
            "schema_version": 1,
            "endpoint_contract_id": contract.contract_id,
            "endpoint_contract_hash": contract.contract_hash,
            "seed_partition_ids": list(self.seed_partition_ids),
            "seed_partitions": [
                offertoday_partition(partition_id).to_payload()
                for partition_id in self.seed_partition_ids
            ],
            "terminal_policy": ENVELOPE_TERMINAL_POLICY_ID,
            "request_policy_hash": phase_c_request_policy_hash(
                self.endpoint_contract_id
            ),
            "max_pages_per_seed": self.max_pages_per_seed,
            "max_attempts_per_page": self.max_attempts_per_page,
            "requested_page_size": self.requested_page_size,
            "listing_logical_budget": self.listing_logical_budget,
            "listing_attempt_budget": self.listing_attempt_budget,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "SupplementalCohortProbePlanV1":
        if not isinstance(payload, Mapping):
            raise ValueError("supplemental probe plan must be a mapping")
        value = cls(
            endpoint_contract_id=payload.get("endpoint_contract_id"),
            seed_partition_ids=_string_tuple(
                payload.get("seed_partition_ids"),
                "seed_partition_ids",
            ),
            max_pages_per_seed=payload.get("max_pages_per_seed"),
            max_attempts_per_page=payload.get("max_attempts_per_page"),
            requested_page_size=payload.get("requested_page_size"),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("supplemental probe plan does not replay")
        return value


@dataclass(frozen=True, slots=True)
class SupplementalSeedConditionEvidenceV1:
    seed_partition_id: str
    condition: PhaseDConditionEvidence

    def __post_init__(self) -> None:
        offertoday_partition(self.seed_partition_id)
        if self.condition.partition_id != self.seed_partition_id:
            raise ValueError("supplemental seed does not match its condition")

    @property
    def supplemental_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for page in _successful_page_attempts(self.condition.pages)
            for job_id in page.cursor_evidence.supplemental_job_ids
        )

    @property
    def result_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for page in _successful_page_attempts(self.condition.pages)
            for job_id in page.cursor_evidence.result_job_ids
        )

    @property
    def cohort_overlap_job_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.result_job_ids) & set(self.supplemental_job_ids))
        )

    @property
    def accepted(self) -> bool:
        return self.condition.accepted and bool(self.supplemental_job_ids)

    def to_payload(self) -> dict[str, Any]:
        return {
            "seed_partition_id": self.seed_partition_id,
            "condition": self.condition.to_payload(),
            "result_job_ids": list(self.result_job_ids),
            "supplemental_job_ids": list(self.supplemental_job_ids),
            "supplemental_set_hash": phase_d_id_set_hash(
                self.supplemental_job_ids
            ),
            "cohort_overlap_job_ids": list(self.cohort_overlap_job_ids),
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "SupplementalSeedConditionEvidenceV1":
        expected = {
            "seed_partition_id",
            "condition",
            "result_job_ids",
            "supplemental_job_ids",
            "supplemental_set_hash",
            "cohort_overlap_job_ids",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("supplemental seed evidence fields do not match")
        value = cls(
            seed_partition_id=payload["seed_partition_id"],
            condition=PhaseDConditionEvidence.from_payload(payload["condition"]),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("supplemental seed evidence does not replay")
        return value


@dataclass(frozen=True, slots=True)
class SupplementalCohortProbeExecutionV1:
    run_id: str
    run_index: int
    captured_at: str
    plan: SupplementalCohortProbePlanV1
    conditions: tuple[SupplementalSeedConditionEvidenceV1, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _canonical_uuid(self.run_id, "run_id")
        if self.run_index not in (1, 2, 3):
            raise ValueError("supplemental run_index must be 1, 2, or 3")
        _aware_datetime(self.captured_at, "captured_at")
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        actual = tuple(item.seed_partition_id for item in self.conditions)
        expected = self.plan.seed_partition_ids
        if actual != expected[: len(actual)]:
            raise ValueError("supplemental seed execution order does not match")
        if self.failure_reason is None and actual != expected:
            raise ValueError("completed supplemental probe requires every seed")
        if self.logical_requests > self.plan.listing_logical_budget:
            raise ValueError("supplemental logical request budget exceeded")
        if self.physical_attempts > self.plan.listing_attempt_budget:
            raise ValueError("supplemental attempt budget exceeded")

    @property
    def logical_requests(self) -> int:
        return sum(item.condition.logical_requests for item in self.conditions)

    @property
    def physical_attempts(self) -> int:
        return sum(item.condition.physical_attempts for item in self.conditions)

    @property
    def supplemental_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for item in self.conditions
            for job_id in item.supplemental_job_ids
        )

    @property
    def result_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id for item in self.conditions for job_id in item.result_job_ids
        )

    @property
    def within_run_min_seed_jaccard(self) -> float:
        return _minimum_pairwise_jaccard(
            tuple(item.supplemental_job_ids for item in self.conditions)
        )

    @property
    def accepted(self) -> bool:
        return (
            self.failure_reason is None
            and bool(self.conditions)
            and all(item.accepted for item in self.conditions)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment": SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "captured_at": self.captured_at,
            "plan": self.plan.to_payload(),
            "plan_hash": self.plan.plan_hash,
            "conditions": [item.to_payload() for item in self.conditions],
            "failure_reason": self.failure_reason,
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "result_job_ids": list(self.result_job_ids),
            "supplemental_job_ids": list(self.supplemental_job_ids),
            "supplemental_set_hash": phase_d_id_set_hash(
                self.supplemental_job_ids
            ),
            "within_run_min_seed_jaccard": (
                self.within_run_min_seed_jaccard
            ),
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "SupplementalCohortProbeExecutionV1":
        expected = {
            "schema_version",
            "experiment",
            "run_id",
            "run_index",
            "captured_at",
            "plan",
            "plan_hash",
            "conditions",
            "failure_reason",
            "logical_requests",
            "physical_attempts",
            "result_job_ids",
            "supplemental_job_ids",
            "supplemental_set_hash",
            "within_run_min_seed_jaccard",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("supplemental probe execution fields do not match")
        if (
            payload["schema_version"] != 1
            or payload["experiment"] != SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT
            or not isinstance(payload["conditions"], list)
        ):
            raise ValueError("supplemental probe execution contract does not match")
        value = cls(
            run_id=payload["run_id"],
            run_index=payload["run_index"],
            captured_at=payload["captured_at"],
            plan=SupplementalCohortProbePlanV1.from_payload(payload["plan"]),
            conditions=tuple(
                SupplementalSeedConditionEvidenceV1.from_payload(item)
                for item in payload["conditions"]
            ),
            failure_reason=payload["failure_reason"],
        )
        if dict(payload) != value.to_payload():
            raise ValueError("supplemental probe execution does not replay")
        return value


@dataclass(frozen=True, slots=True)
class SupplementalCohortDecisionV1:
    accepted: bool
    failing_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be an exact boolean")
        if self.accepted != (not self.failing_gates):
            raise ValueError("supplemental decision does not match failing gates")

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "failing_gates": list(self.failing_gates),
        }


@dataclass(frozen=True, slots=True)
class SupplementalCohortStabilityComparisonV1:
    plan_hash: str
    run_ids: tuple[str, ...]
    within_run_min_seed_jaccards: tuple[tuple[str, float], ...]
    within_seed_min_run_jaccards: tuple[tuple[str, float], ...]
    cross_seed_min_jaccard: float
    cross_run_min_jaccard: float
    diagnostic_union_ids: tuple[str, ...]
    stable_supplemental_ids: tuple[str, ...]
    result_reference_ids: tuple[str, ...]
    overlap_with_result_ids: tuple[str, ...]
    unique_contribution_ids: tuple[str, ...]
    unique_contribution_ratio: float
    decision: SupplementalCohortDecisionV1

    def __post_init__(self) -> None:
        _sha256(self.plan_hash, "plan_hash")
        if len(self.run_ids) != 3 or len(set(self.run_ids)) != 3:
            raise ValueError("supplemental comparison needs three distinct runs")
        for run_id in self.run_ids:
            _canonical_uuid(run_id, "run_id")
        for _, value in (
            *self.within_run_min_seed_jaccards,
            *self.within_seed_min_run_jaccards,
        ):
            _finite_ratio(value, "minimum_jaccard")
        _finite_ratio(self.cross_seed_min_jaccard, "cross_seed_min_jaccard")
        _finite_ratio(self.cross_run_min_jaccard, "cross_run_min_jaccard")
        _finite_ratio(
            self.unique_contribution_ratio,
            "unique_contribution_ratio",
        )
        for field_name in (
            "diagnostic_union_ids",
            "stable_supplemental_ids",
            "result_reference_ids",
            "overlap_with_result_ids",
            "unique_contribution_ids",
        ):
            values = getattr(self, field_name)
            if values != _canonical_ids(values):
                raise ValueError(f"{field_name} must be canonical")
        if self.overlap_with_result_ids != tuple(
            sorted(set(self.stable_supplemental_ids) & set(self.result_reference_ids))
        ):
            raise ValueError("supplemental/result overlap does not match")
        if self.unique_contribution_ids != tuple(
            sorted(set(self.stable_supplemental_ids) - set(self.result_reference_ids))
        ):
            raise ValueError("supplemental unique contribution does not match")

    @property
    def policy_hash(self) -> str:
        return canonical_dual_cohort_hash(
            {
                "policy_version": 1,
                "plan_hash": self.plan_hash,
                "terminal_policy": ENVELOPE_TERMINAL_POLICY_ID,
                "minimum_jaccard": SUPPLEMENTAL_MIN_JACCARD,
                "minimum_contribution_ratio": (
                    SUPPLEMENTAL_MIN_CONTRIBUTION_RATIO
                ),
                "stable_supplemental_ids": list(
                    self.stable_supplemental_ids
                ),
                "stable_supplemental_hash": phase_d_id_set_hash(
                    self.stable_supplemental_ids
                ),
            }
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "plan_hash": self.plan_hash,
            "run_ids": list(self.run_ids),
            "within_run_min_seed_jaccards": [
                {"run_id": key, "jaccard": value}
                for key, value in self.within_run_min_seed_jaccards
            ],
            "within_seed_min_run_jaccards": [
                {"partition_id": key, "jaccard": value}
                for key, value in self.within_seed_min_run_jaccards
            ],
            "cross_seed_min_jaccard": self.cross_seed_min_jaccard,
            "cross_run_min_jaccard": self.cross_run_min_jaccard,
            "diagnostic_union_ids": list(self.diagnostic_union_ids),
            "diagnostic_union_hash": phase_d_id_set_hash(
                self.diagnostic_union_ids
            ),
            "stable_supplemental_ids": list(self.stable_supplemental_ids),
            "stable_supplemental_hash": phase_d_id_set_hash(
                self.stable_supplemental_ids
            ),
            "result_reference_ids": list(self.result_reference_ids),
            "result_reference_hash": phase_d_id_set_hash(
                self.result_reference_ids
            ),
            "overlap_with_result_ids": list(self.overlap_with_result_ids),
            "unique_contribution_ids": list(self.unique_contribution_ids),
            "unique_contribution_ratio": self.unique_contribution_ratio,
            "policy_hash": self.policy_hash,
            "decision": self.decision.to_payload(),
        }


def compare_supplemental_cohort_probes_v1(
    probes: Sequence[SupplementalCohortProbeExecutionV1],
) -> SupplementalCohortStabilityComparisonV1:
    items = tuple(probes)
    if len(items) != 3:
        raise ValueError("supplemental comparison requires exactly three probes")
    if tuple(item.run_index for item in items) != (1, 2, 3):
        raise ValueError("supplemental run indexes must be 1, 2, 3")
    if len({item.run_id for item in items}) != 3:
        raise ValueError("supplemental run IDs must be distinct")
    if len({item.plan.plan_hash for item in items}) != 1:
        raise ValueError("supplemental probes must share one plan")

    by_run = tuple(
        (item.run_id, item.within_run_min_seed_jaccard) for item in items
    )
    by_seed = tuple(
        (
            partition_id,
            _minimum_pairwise_jaccard(
                tuple(
                    next(
                        condition.supplemental_job_ids
                        for condition in probe.conditions
                        if condition.seed_partition_id == partition_id
                    )
                    for probe in items
                )
            ),
        )
        for partition_id in items[0].plan.seed_partition_ids
    )
    cross_seed_min = min(value for _, value in by_run)
    cross_run_min = min(value for _, value in by_seed)
    diagnostic_union = _canonical_ids(
        job_id
        for probe in items
        for job_id in probe.supplemental_job_ids
    )
    result_reference = _canonical_ids(
        job_id for probe in items for job_id in probe.result_job_ids
    )

    run_membership: dict[str, set[str]] = {}
    seed_membership: dict[str, set[str]] = {}
    for probe in items:
        for condition in probe.conditions:
            for job_id in condition.supplemental_job_ids:
                run_membership.setdefault(job_id, set()).add(probe.run_id)
                seed_membership.setdefault(job_id, set()).add(
                    condition.seed_partition_id
                )
    stable = _canonical_ids(
        job_id
        for job_id in diagnostic_union
        if len(run_membership.get(job_id, ())) >= 2
        and len(seed_membership.get(job_id, ())) >= 2
    )
    overlap = tuple(sorted(set(stable) & set(result_reference)))
    unique = tuple(sorted(set(stable) - set(result_reference)))
    contribution_ratio = (
        len(unique) / len(result_reference)
        if result_reference
        else (1.0 if unique else 0.0)
    )

    failing_gates: list[str] = []
    if not all(item.accepted for item in items):
        failing_gates.append("all_three_probes_accepted")
    if cross_seed_min < SUPPLEMENTAL_MIN_JACCARD:
        failing_gates.append("cross_seed_jaccard")
    if cross_run_min < SUPPLEMENTAL_MIN_JACCARD:
        failing_gates.append("cross_run_jaccard")
    if not stable:
        failing_gates.append("nonempty_stable_supplemental_cohort")
    if not unique:
        failing_gates.append("nonempty_unique_contribution")
    if contribution_ratio < SUPPLEMENTAL_MIN_CONTRIBUTION_RATIO:
        failing_gates.append("unique_contribution_ratio")

    decision = SupplementalCohortDecisionV1(
        accepted=not failing_gates,
        failing_gates=tuple(failing_gates),
    )
    return SupplementalCohortStabilityComparisonV1(
        plan_hash=items[0].plan.plan_hash,
        run_ids=tuple(item.run_id for item in items),
        within_run_min_seed_jaccards=by_run,
        within_seed_min_run_jaccards=by_seed,
        cross_seed_min_jaccard=cross_seed_min,
        cross_run_min_jaccard=cross_run_min,
        diagnostic_union_ids=diagnostic_union,
        stable_supplemental_ids=stable,
        result_reference_ids=result_reference,
        overlap_with_result_ids=overlap,
        unique_contribution_ids=unique,
        unique_contribution_ratio=contribution_ratio,
        decision=decision,
    )


def supplemental_cohort_comparison_payload_v1(
    probes: Sequence[SupplementalCohortProbeExecutionV1],
) -> dict[str, Any]:
    items = tuple(probes)
    comparison = compare_supplemental_cohort_probes_v1(items)
    inputs = [item.to_payload() for item in items]
    return {
        "schema_version": 1,
        "experiment": SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
        "inputs": inputs,
        "input_set_hash": canonical_dual_cohort_hash(inputs),
        "comparison": comparison.to_payload(),
        "comparison_hash": canonical_dual_cohort_hash(comparison.to_payload()),
        "policy_frozen": comparison.decision.accepted,
    }


def validate_supplemental_cohort_comparison_payload_v1(
    payload: Any,
) -> SupplementalCohortStabilityComparisonV1:
    expected = {
        "schema_version",
        "experiment",
        "inputs",
        "input_set_hash",
        "comparison",
        "comparison_hash",
        "policy_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("supplemental comparison payload fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT
        or not isinstance(payload["inputs"], list)
    ):
        raise ValueError("supplemental comparison contract does not match")
    probes = tuple(
        SupplementalCohortProbeExecutionV1.from_payload(item)
        for item in payload["inputs"]
    )
    comparison = compare_supplemental_cohort_probes_v1(probes)
    expected_payload = supplemental_cohort_comparison_payload_v1(probes)
    if dict(payload) != expected_payload:
        raise ValueError("supplemental comparison does not replay")
    return comparison


@dataclass(frozen=True, slots=True)
class SupplementalGateStateV1:
    status: str
    artifact_hash: str | None
    comparison_hash: str | None
    failing_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"missing", "rejected"}:
            raise ValueError("partial supplemental gate must be missing or rejected")
        if self.status == "missing":
            if self.artifact_hash is not None or self.comparison_hash is not None:
                raise ValueError("missing supplemental gate cannot claim parent hashes")
        else:
            _sha256(self.artifact_hash, "supplemental artifact_hash")
            _sha256(self.comparison_hash, "supplemental comparison_hash")
        if not self.failing_gates or any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            for value in self.failing_gates
        ):
            raise ValueError("unresolved supplemental gate needs failing_gates")

    @property
    def gate_hash(self) -> str:
        return canonical_dual_cohort_hash(self._canonical_payload())

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "gate_version": 1,
            "experiment": SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
            "status": self.status,
            "artifact_hash": self.artifact_hash,
            "comparison_hash": self.comparison_hash,
            "failing_gates": list(self.failing_gates),
            "accepted": False,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "gate_hash": self.gate_hash}

    @classmethod
    def from_payload(cls, payload: Any) -> "SupplementalGateStateV1":
        expected = {
            "gate_version",
            "experiment",
            "status",
            "artifact_hash",
            "comparison_hash",
            "failing_gates",
            "accepted",
            "gate_hash",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("supplemental gate state fields do not match")
        if (
            payload["gate_version"] != 1
            or payload["experiment"]
            != SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT
            or payload["accepted"] is not False
        ):
            raise ValueError("supplemental gate state contract does not match")
        value = cls(
            status=payload["status"],
            artifact_hash=payload["artifact_hash"],
            comparison_hash=payload["comparison_hash"],
            failing_gates=_string_tuple(
                payload["failing_gates"],
                "failing_gates",
            ),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("supplemental gate state does not replay")
        return value


@dataclass(frozen=True, slots=True)
class ResultOnlyDiscoveryScopeV3:
    result_policy: ResultPartitionPolicyV1
    result_policy_artifact_hash: str
    supplemental_gate: SupplementalGateStateV1
    phase_b_comparison_artifact_hash: str

    def __post_init__(self) -> None:
        _sha256(self.result_policy_artifact_hash, "result_policy_artifact_hash")
        _sha256(
            self.phase_b_comparison_artifact_hash,
            "phase_b_comparison_artifact_hash",
        )

    @property
    def phase_d_partition_ids(self) -> tuple[str, ...]:
        return tuple(
            top_level_partition(category.code).partition_id
            for category in OFFERTODAY_CATEGORIES_L1
        )

    def _canonical_payload(self) -> dict[str, Any]:
        contract = offertoday_endpoint_contract(
            self.result_policy.endpoint_contract_id
        )
        return {
            "scope_version": 3,
            "cohort_scope": "result-only-partial",
            "endpoint_contract_id": contract.contract_id,
            "endpoint_contract_hash": contract.contract_hash,
            "endpoint": contract.endpoint,
            "rcd_type": None,
            "category_catalog_version": OFFERTODAY_CATEGORY_CATALOG_VERSION,
            "category_catalog_hash": offertoday_category_catalog_hash(),
            "partition_catalog_hash": offertoday_partition_catalog_hash(),
            "phase_d_partition_ids": list(self.phase_d_partition_ids),
            "fixed_repeat_category_ids": list(
                DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS
            ),
            "result_policy": self.result_policy.to_payload(),
            "result_policy_hash": self.result_policy.policy_hash,
            "result_policy_artifact_hash": self.result_policy_artifact_hash,
            "supplemental_gate": self.supplemental_gate.to_payload(),
            "supplemental_gate_hash": self.supplemental_gate.gate_hash,
            "pagination_mode": "response-cursor",
            "requested_page_size": DUAL_COHORT_REQUESTED_PAGE_SIZE,
            "browser_lifecycle": "condition-local-runtime",
            "request_policy_hash": phase_c_request_policy_hash(
                contract.contract_id
            ),
            "result_terminal_policy": RESULT_TERMINAL_POLICY_ID,
            "max_pages_per_condition": (
                DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION
            ),
            "max_attempts_per_page": DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE,
            "retry_delays_seconds": list(
                DUAL_COHORT_PHASE_D_RETRY_DELAYS_SECONDS
            ),
            "page_delay_range_seconds": list(
                DUAL_COHORT_PHASE_D_PAGE_DELAY_RANGE_SECONDS
            ),
            "session_mode": DUAL_COHORT_PHASE_D_SESSION_MODE,
            "phase_b_comparison_artifact_hash": (
                self.phase_b_comparison_artifact_hash
            ),
            "deferred_issue_ids": list(DUAL_COHORT_DEFERRED_ISSUE_IDS),
            "complete_candidate": False,
            "downstream_eligible": False,
        }

    @property
    def scope_hash(self) -> str:
        return canonical_dual_cohort_hash(self._canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "scope_hash": self.scope_hash}

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultOnlyDiscoveryScopeV3":
        if not isinstance(payload, Mapping):
            raise ValueError("result-only scope must be a mapping")
        if (
            payload.get("scope_version") != 3
            or payload.get("cohort_scope") != "result-only-partial"
            or payload.get("complete_candidate") is not False
            or payload.get("downstream_eligible") is not False
        ):
            raise ValueError("result-only scope contract does not match v3")
        value = cls(
            result_policy=ResultPartitionPolicyV1.from_payload(
                payload.get("result_policy")
            ),
            result_policy_artifact_hash=payload.get(
                "result_policy_artifact_hash"
            ),
            supplemental_gate=SupplementalGateStateV1.from_payload(
                payload.get("supplemental_gate")
            ),
            phase_b_comparison_artifact_hash=payload.get(
                "phase_b_comparison_artifact_hash"
            ),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("result-only scope does not replay")
        return value


@dataclass(frozen=True, slots=True)
class DualCohortDiscoveryPolicyCandidateV3:
    endpoint_contract_id: str
    endpoint_contract_hash: str
    result_partition_policy_hash: str
    result_partition_policy_artifact_hash: str
    supplemental_cohort_policy_hash: str
    supplemental_comparison_artifact_hash: str
    supplemental_source_payload_hash: str
    supplemental_stable_ids_hash: str
    supplemental_canonical_seed_partition_id: str
    phase_b_comparison_artifact_hash: str

    def __post_init__(self) -> None:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("dual-cohort candidate endpoint hash does not match")
        if not contract.cursor_verified or not contract.terminal_verified:
            raise ValueError("dual-cohort candidate requires a verified endpoint")
        for field_name in (
            "result_partition_policy_hash",
            "result_partition_policy_artifact_hash",
            "supplemental_cohort_policy_hash",
            "supplemental_comparison_artifact_hash",
            "supplemental_source_payload_hash",
            "supplemental_stable_ids_hash",
            "phase_b_comparison_artifact_hash",
        ):
            _sha256(getattr(self, field_name), field_name)
        if (
            self.supplemental_canonical_seed_partition_id
            != SUPPLEMENTAL_SEED_PARTITION_IDS[0]
        ):
            raise ValueError("dual-cohort canonical supplemental seed does not match")

    @property
    def phase_d_partition_ids(self) -> tuple[str, ...]:
        return tuple(
            top_level_partition(category.code).partition_id
            for category in OFFERTODAY_CATEGORIES_L1
        )

    def _canonical_payload(self) -> dict[str, Any]:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        return {
            "candidate_version": 3,
            "cohort_scope": "complete-dual-cohort",
            "endpoint_contract_id": contract.contract_id,
            "endpoint_contract_hash": contract.contract_hash,
            "endpoint": contract.endpoint,
            "rcd_type": None,
            "category_catalog_version": OFFERTODAY_CATEGORY_CATALOG_VERSION,
            "category_catalog_hash": offertoday_category_catalog_hash(),
            "partition_catalog_hash": offertoday_partition_catalog_hash(),
            "phase_d_partition_ids": list(self.phase_d_partition_ids),
            "fixed_repeat_category_ids": list(
                DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS
            ),
            "result_partition_policy_hash": self.result_partition_policy_hash,
            "result_partition_policy_artifact_hash": (
                self.result_partition_policy_artifact_hash
            ),
            "supplemental_cohort_policy_hash": (
                self.supplemental_cohort_policy_hash
            ),
            "supplemental_comparison_artifact_hash": (
                self.supplemental_comparison_artifact_hash
            ),
            "supplemental_source_payload_hash": (
                self.supplemental_source_payload_hash
            ),
            "supplemental_stable_ids_hash": self.supplemental_stable_ids_hash,
            "supplemental_canonical_seed_partition_id": (
                self.supplemental_canonical_seed_partition_id
            ),
            "pagination_mode": "response-cursor",
            "requested_page_size": DUAL_COHORT_REQUESTED_PAGE_SIZE,
            "browser_lifecycle": "condition-local-runtime",
            "request_policy_hash": phase_c_request_policy_hash(
                contract.contract_id
            ),
            "result_terminal_policy": RESULT_TERMINAL_POLICY_ID,
            "supplemental_terminal_policy": ENVELOPE_TERMINAL_POLICY_ID,
            "max_pages_per_condition": (
                DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION
            ),
            "max_supplemental_pages": (
                DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION
            ),
            "max_attempts_per_page": DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE,
            "retry_delays_seconds": list(
                DUAL_COHORT_PHASE_D_RETRY_DELAYS_SECONDS
            ),
            "page_delay_range_seconds": list(
                DUAL_COHORT_PHASE_D_PAGE_DELAY_RANGE_SECONDS
            ),
            "session_mode": DUAL_COHORT_PHASE_D_SESSION_MODE,
            "phase_b_comparison_artifact_hash": (
                self.phase_b_comparison_artifact_hash
            ),
            "deferred_issue_ids": list(DUAL_COHORT_DEFERRED_ISSUE_IDS),
            "complete_candidate": True,
            "downstream_eligible": True,
        }

    @property
    def candidate_hash(self) -> str:
        return canonical_dual_cohort_hash(self._canonical_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            **self._canonical_payload(),
            "candidate_hash": self.candidate_hash,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "DualCohortDiscoveryPolicyCandidateV3":
        if not isinstance(payload, Mapping):
            raise ValueError("dual-cohort candidate must be a mapping")
        if (
            payload.get("candidate_version") != 3
            or payload.get("cohort_scope") != "complete-dual-cohort"
            or payload.get("complete_candidate") is not True
            or payload.get("downstream_eligible") is not True
        ):
            raise ValueError("dual-cohort candidate contract does not match v3")
        value = cls(
            endpoint_contract_id=payload.get("endpoint_contract_id"),
            endpoint_contract_hash=payload.get("endpoint_contract_hash"),
            result_partition_policy_hash=payload.get(
                "result_partition_policy_hash"
            ),
            result_partition_policy_artifact_hash=payload.get(
                "result_partition_policy_artifact_hash"
            ),
            supplemental_cohort_policy_hash=payload.get(
                "supplemental_cohort_policy_hash"
            ),
            supplemental_comparison_artifact_hash=payload.get(
                "supplemental_comparison_artifact_hash"
            ),
            supplemental_source_payload_hash=payload.get(
                "supplemental_source_payload_hash"
            ),
            supplemental_stable_ids_hash=payload.get(
                "supplemental_stable_ids_hash"
            ),
            supplemental_canonical_seed_partition_id=payload.get(
                "supplemental_canonical_seed_partition_id"
            ),
            phase_b_comparison_artifact_hash=payload.get(
                "phase_b_comparison_artifact_hash"
            ),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("dual-cohort candidate does not replay")
        return value


def build_dual_cohort_discovery_candidate_v3(
    *,
    result_policy: ResultPartitionPolicyV1,
    result_policy_artifact_hash: str,
    supplemental_comparison_payload: Mapping[str, Any],
    supplemental_comparison_artifact_hash: str,
    phase_b_comparison_artifact_hash: str,
) -> DualCohortDiscoveryPolicyCandidateV3:
    comparison = validate_supplemental_cohort_comparison_payload_v1(
        supplemental_comparison_payload
    )
    if not comparison.decision.accepted:
        raise ValueError("dual-cohort candidate requires accepted supplemental evidence")
    raw_inputs = supplemental_comparison_payload["inputs"]
    probes = tuple(
        SupplementalCohortProbeExecutionV1.from_payload(item)
        for item in raw_inputs
    )
    endpoint_ids = {probe.plan.endpoint_contract_id for probe in probes}
    if endpoint_ids != {result_policy.endpoint_contract_id}:
        raise ValueError("dual-cohort policy endpoints do not match")
    contract = offertoday_endpoint_contract(result_policy.endpoint_contract_id)
    return DualCohortDiscoveryPolicyCandidateV3(
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        result_partition_policy_hash=result_policy.policy_hash,
        result_partition_policy_artifact_hash=result_policy_artifact_hash,
        supplemental_cohort_policy_hash=comparison.policy_hash,
        supplemental_comparison_artifact_hash=(
            supplemental_comparison_artifact_hash
        ),
        supplemental_source_payload_hash=canonical_dual_cohort_hash(
            dict(supplemental_comparison_payload)
        ),
        supplemental_stable_ids_hash=phase_d_id_set_hash(
            comparison.stable_supplemental_ids
        ),
        supplemental_canonical_seed_partition_id=(
            SUPPLEMENTAL_SEED_PARTITION_IDS[0]
        ),
        phase_b_comparison_artifact_hash=phase_b_comparison_artifact_hash,
    )


def dual_cohort_candidate_artifact_payload_v3(
    *,
    candidate: DualCohortDiscoveryPolicyCandidateV3,
    result_policy: ResultPartitionPolicyV1,
    supplemental_comparison_payload: Mapping[str, Any],
) -> dict[str, Any]:
    comparison = validate_supplemental_cohort_comparison_payload_v1(
        supplemental_comparison_payload
    )
    if (
        not comparison.decision.accepted
        or result_policy.policy_hash != candidate.result_partition_policy_hash
        or comparison.policy_hash != candidate.supplemental_cohort_policy_hash
        or canonical_dual_cohort_hash(dict(supplemental_comparison_payload))
        != candidate.supplemental_source_payload_hash
        or phase_d_id_set_hash(comparison.stable_supplemental_ids)
        != candidate.supplemental_stable_ids_hash
    ):
        raise ValueError("dual-cohort candidate parent projections do not match")
    candidate_payload = candidate.to_payload()
    result_payload = result_policy.to_payload()
    supplemental_payload = dict(supplemental_comparison_payload)
    return {
        "schema_version": 1,
        "experiment": DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT,
        "candidate": candidate_payload,
        "candidate_hash": candidate.candidate_hash,
        "result_policy_projection": result_payload,
        "result_policy_projection_hash": canonical_dual_cohort_hash(
            result_payload
        ),
        "supplemental_comparison_projection": supplemental_payload,
        "supplemental_comparison_projection_hash": (
            canonical_dual_cohort_hash(supplemental_payload)
        ),
        "candidate_frozen": True,
        "downstream_eligible": True,
    }


def validate_dual_cohort_candidate_artifact_payload_v3(
    payload: Any,
) -> DualCohortDiscoveryPolicyCandidateV3:
    expected = {
        "schema_version",
        "experiment",
        "candidate",
        "candidate_hash",
        "result_policy_projection",
        "result_policy_projection_hash",
        "supplemental_comparison_projection",
        "supplemental_comparison_projection_hash",
        "candidate_frozen",
        "downstream_eligible",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("dual-cohort candidate artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"]
        != DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT
        or payload["candidate_frozen"] is not True
        or payload["downstream_eligible"] is not True
    ):
        raise ValueError("dual-cohort candidate artifact contract does not match")
    candidate = DualCohortDiscoveryPolicyCandidateV3.from_payload(
        payload["candidate"]
    )
    result_policy = ResultPartitionPolicyV1.from_payload(
        payload["result_policy_projection"]
    )
    expected_payload = dual_cohort_candidate_artifact_payload_v3(
        candidate=candidate,
        result_policy=result_policy,
        supplemental_comparison_payload=payload[
            "supplemental_comparison_projection"
        ],
    )
    if dict(payload) != expected_payload:
        raise ValueError("dual-cohort candidate artifact does not replay")
    return candidate


def _expected_phase_d_category_ids(experiment: str) -> tuple[int, ...]:
    if experiment in {
        RESULT_PARTIAL_CENSUS_EXPERIMENT,
        DUAL_COHORT_CENSUS_EXPERIMENT,
    }:
        return tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
    if experiment in {
        RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    }:
        return DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS
    raise ValueError("unsupported dual-cohort Phase D run experiment")


@dataclass(frozen=True, slots=True)
class ResultPartialPhaseDRunV3:
    experiment: str
    run_id: str
    run_index: int
    window_id: str
    captured_at: str
    scope_hash: str
    duration_seconds: float
    conditions: tuple[ResultPartitionConditionEvidenceV2, ...]
    product: PhaseDProductEvidence
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.experiment not in {
            RESULT_PARTIAL_CENSUS_EXPERIMENT,
            RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
        }:
            raise ValueError("unsupported result-only partial run experiment")
        _canonical_uuid(self.run_id, "run_id")
        if self.run_index not in (1, 2, 3):
            raise ValueError("partial run_index must be 1, 2, or 3")
        _nonblank(self.window_id, "window_id")
        _aware_datetime(self.captured_at, "captured_at")
        _sha256(self.scope_hash, "scope_hash")
        _finite_nonnegative(self.duration_seconds, "duration_seconds")
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        expected = _expected_phase_d_category_ids(self.experiment)
        actual = tuple(item.condition.category_id for item in self.conditions)
        if actual != expected[: len(actual)]:
            raise ValueError("partial result condition order does not match")
        if self.failure_reason is None and actual != expected:
            raise ValueError("completed partial run requires every result condition")

    @property
    def result_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for item in self.conditions
            for job_id in item.terminal.result_job_ids
        )

    @property
    def observed_supplemental_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for item in self.conditions
            for job_id in item.terminal.supplemental_job_ids
        )

    @property
    def cohort_overlap_job_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.result_job_ids)
                & set(self.observed_supplemental_job_ids)
            )
        )

    @property
    def logical_requests(self) -> int:
        return sum(item.condition.logical_requests for item in self.conditions)

    @property
    def physical_attempts(self) -> int:
        return sum(item.condition.physical_attempts for item in self.conditions)

    @property
    def partial_research_complete(self) -> bool:
        return (
            self.failure_reason is None
            and bool(self.conditions)
            and all(item.accepted for item in self.conditions)
            and self.product.accepted
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment": self.experiment,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "window_id": self.window_id,
            "captured_at": self.captured_at,
            "scope_hash": self.scope_hash,
            "duration_seconds": float(self.duration_seconds),
            "conditions": [item.to_payload() for item in self.conditions],
            "product": self.product.to_payload(),
            "failure_reason": self.failure_reason,
            "result_job_ids": list(self.result_job_ids),
            "result_set_hash": phase_d_id_set_hash(self.result_job_ids),
            "observed_supplemental_job_ids": list(
                self.observed_supplemental_job_ids
            ),
            "observed_supplemental_set_hash": phase_d_id_set_hash(
                self.observed_supplemental_job_ids
            ),
            "cohort_overlap_job_ids": list(self.cohort_overlap_job_ids),
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "partial_research_complete": self.partial_research_complete,
            "cohort_scope": "result-only-partial",
            "accepted": False,
            "stable_reference_frozen": False,
            "downstream_eligible": False,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "ResultPartialPhaseDRunV3":
        if not isinstance(payload, Mapping):
            raise ValueError("partial Phase D run must be a mapping")
        if (
            payload.get("schema_version") != 1
            or payload.get("cohort_scope") != "result-only-partial"
            or payload.get("accepted") is not False
            or payload.get("stable_reference_frozen") is not False
            or payload.get("downstream_eligible") is not False
            or not isinstance(payload.get("conditions"), list)
        ):
            raise ValueError("partial Phase D run contract does not match v3")
        value = cls(
            experiment=payload.get("experiment"),
            run_id=payload.get("run_id"),
            run_index=payload.get("run_index"),
            window_id=payload.get("window_id"),
            captured_at=payload.get("captured_at"),
            scope_hash=payload.get("scope_hash"),
            duration_seconds=payload.get("duration_seconds"),
            conditions=tuple(
                ResultPartitionConditionEvidenceV2.from_payload(item)
                for item in payload["conditions"]
            ),
            product=PhaseDProductEvidence.from_payload(payload.get("product")),
            failure_reason=payload.get("failure_reason"),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("partial Phase D run does not replay")
        return value


def result_partial_phase_d_artifact_payload_v3(
    *,
    run: ResultPartialPhaseDRunV3,
    scope: ResultOnlyDiscoveryScopeV3,
    baseline: PhaseCBaselineReference,
) -> dict[str, Any]:
    if run.scope_hash != scope.scope_hash:
        raise ValueError("partial run scope hash does not match")
    if any(
        item.condition.endpoint_contract_id
        != scope.result_policy.endpoint_contract_id
        or item.condition.endpoint_contract_hash
        != scope.result_policy.endpoint_contract_hash
        for item in run.conditions
    ):
        raise ValueError("partial result condition endpoint does not match scope")
    logical_budget = (
        len(_expected_phase_d_category_ids(run.experiment))
        * DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION
    )
    if (
        run.logical_requests > logical_budget
        or run.physical_attempts
        > logical_budget * DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE
    ):
        raise ValueError("partial Phase D request budget exceeded")
    run_payload = run.to_payload()
    scope_payload = scope.to_payload()
    return {
        "schema_version": 1,
        "experiment": run.experiment,
        "scope_projection": scope_payload,
        "scope_hash": scope.scope_hash,
        "baseline": baseline.to_payload(),
        "run": run_payload,
        "run_hash": canonical_dual_cohort_hash(run_payload),
        "partial_research_complete": run.partial_research_complete,
        "accepted": False,
        "stable_reference_frozen": False,
        "downstream_eligible": False,
    }


def validate_result_partial_phase_d_artifact_payload_v3(
    payload: Any,
) -> tuple[
    ResultPartialPhaseDRunV3,
    ResultOnlyDiscoveryScopeV3,
    PhaseCBaselineReference,
]:
    expected = {
        "schema_version",
        "experiment",
        "scope_projection",
        "scope_hash",
        "baseline",
        "run",
        "run_hash",
        "partial_research_complete",
        "accepted",
        "stable_reference_frozen",
        "downstream_eligible",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("partial Phase D artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"]
        not in {
            RESULT_PARTIAL_CENSUS_EXPERIMENT,
            RESULT_PARTIAL_FIXED_REPEAT_EXPERIMENT,
        }
        or payload["accepted"] is not False
        or payload["stable_reference_frozen"] is not False
        or payload["downstream_eligible"] is not False
    ):
        raise ValueError("partial Phase D artifact contract does not match v3")
    scope = ResultOnlyDiscoveryScopeV3.from_payload(payload["scope_projection"])
    baseline = PhaseCBaselineReference.from_payload(payload["baseline"])
    run = ResultPartialPhaseDRunV3.from_payload(payload["run"])
    expected_payload = result_partial_phase_d_artifact_payload_v3(
        run=run,
        scope=scope,
        baseline=baseline,
    )
    if dict(payload) != expected_payload:
        raise ValueError("partial Phase D artifact does not replay")
    return run, scope, baseline


@dataclass(frozen=True, slots=True)
class DualCohortPhaseDRunV3:
    experiment: str
    run_id: str
    run_index: int
    window_id: str
    captured_at: str
    candidate_hash: str
    candidate_artifact_hash: str
    duration_seconds: float
    result_conditions: tuple[ResultPartitionConditionEvidenceV2, ...]
    supplemental_condition: SupplementalSeedConditionEvidenceV1 | None
    product: PhaseDProductEvidence
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.experiment not in {
            DUAL_COHORT_CENSUS_EXPERIMENT,
            DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
        }:
            raise ValueError("unsupported complete dual-cohort run experiment")
        _canonical_uuid(self.run_id, "run_id")
        if self.run_index not in (1, 2, 3):
            raise ValueError("complete run_index must be 1, 2, or 3")
        _nonblank(self.window_id, "window_id")
        _aware_datetime(self.captured_at, "captured_at")
        _sha256(self.candidate_hash, "candidate_hash")
        _sha256(self.candidate_artifact_hash, "candidate_artifact_hash")
        _finite_nonnegative(self.duration_seconds, "duration_seconds")
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        expected = _expected_phase_d_category_ids(self.experiment)
        actual = tuple(
            item.condition.category_id for item in self.result_conditions
        )
        if actual != expected[: len(actual)]:
            raise ValueError("complete result condition order does not match")
        if self.failure_reason is None and (
            actual != expected or self.supplemental_condition is None
        ):
            raise ValueError("complete run requires all result and supplemental evidence")

    @property
    def result_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id
            for item in self.result_conditions
            for job_id in item.terminal.result_job_ids
        )

    @property
    def supplemental_job_ids(self) -> tuple[str, ...]:
        if self.supplemental_condition is None:
            return ()
        return self.supplemental_condition.supplemental_job_ids

    @property
    def cohort_overlap_job_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.result_job_ids) & set(self.supplemental_job_ids))
        )

    @property
    def combined_job_ids(self) -> tuple[str, ...]:
        return _canonical_ids((*self.result_job_ids, *self.supplemental_job_ids))

    @property
    def logical_requests(self) -> int:
        result_requests = sum(
            item.condition.logical_requests for item in self.result_conditions
        )
        supplemental_requests = (
            0
            if self.supplemental_condition is None
            else self.supplemental_condition.condition.logical_requests
        )
        return result_requests + supplemental_requests

    @property
    def physical_attempts(self) -> int:
        result_attempts = sum(
            item.condition.physical_attempts for item in self.result_conditions
        )
        supplemental_attempts = (
            0
            if self.supplemental_condition is None
            else self.supplemental_condition.condition.physical_attempts
        )
        return result_attempts + supplemental_attempts

    @property
    def accepted(self) -> bool:
        return (
            self.failure_reason is None
            and bool(self.result_conditions)
            and all(item.accepted for item in self.result_conditions)
            and self.supplemental_condition is not None
            and self.supplemental_condition.accepted
            and self.product.accepted
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment": self.experiment,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "window_id": self.window_id,
            "captured_at": self.captured_at,
            "candidate_hash": self.candidate_hash,
            "candidate_artifact_hash": self.candidate_artifact_hash,
            "duration_seconds": float(self.duration_seconds),
            "result_conditions": [
                item.to_payload() for item in self.result_conditions
            ],
            "supplemental_condition": (
                None
                if self.supplemental_condition is None
                else self.supplemental_condition.to_payload()
            ),
            "product": self.product.to_payload(),
            "failure_reason": self.failure_reason,
            "result_job_ids": list(self.result_job_ids),
            "result_set_hash": phase_d_id_set_hash(self.result_job_ids),
            "supplemental_job_ids": list(self.supplemental_job_ids),
            "supplemental_set_hash": phase_d_id_set_hash(
                self.supplemental_job_ids
            ),
            "cohort_overlap_job_ids": list(self.cohort_overlap_job_ids),
            "cohort_overlap_hash": phase_d_id_set_hash(
                self.cohort_overlap_job_ids
            ),
            "combined_job_ids": list(self.combined_job_ids),
            "combined_set_hash": phase_d_id_set_hash(self.combined_job_ids),
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "cohort_scope": "complete-dual-cohort",
            "accepted": self.accepted,
            "downstream_eligible": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "DualCohortPhaseDRunV3":
        if not isinstance(payload, Mapping):
            raise ValueError("complete dual-cohort run must be a mapping")
        if (
            payload.get("schema_version") != 1
            or payload.get("cohort_scope") != "complete-dual-cohort"
            or not isinstance(payload.get("result_conditions"), list)
        ):
            raise ValueError("complete dual-cohort run contract does not match v3")
        raw_supplemental = payload.get("supplemental_condition")
        value = cls(
            experiment=payload.get("experiment"),
            run_id=payload.get("run_id"),
            run_index=payload.get("run_index"),
            window_id=payload.get("window_id"),
            captured_at=payload.get("captured_at"),
            candidate_hash=payload.get("candidate_hash"),
            candidate_artifact_hash=payload.get("candidate_artifact_hash"),
            duration_seconds=payload.get("duration_seconds"),
            result_conditions=tuple(
                ResultPartitionConditionEvidenceV2.from_payload(item)
                for item in payload["result_conditions"]
            ),
            supplemental_condition=(
                None
                if raw_supplemental is None
                else SupplementalSeedConditionEvidenceV1.from_payload(
                    raw_supplemental
                )
            ),
            product=PhaseDProductEvidence.from_payload(payload.get("product")),
            failure_reason=payload.get("failure_reason"),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("complete dual-cohort run does not replay")
        return value


def dual_cohort_phase_d_run_artifact_payload_v3(
    *,
    run: DualCohortPhaseDRunV3,
    candidate: DualCohortDiscoveryPolicyCandidateV3,
    baseline: PhaseCBaselineReference,
) -> dict[str, Any]:
    if run.candidate_hash != candidate.candidate_hash:
        raise ValueError("dual-cohort run candidate hash does not match")
    if any(
        item.condition.endpoint_contract_id != candidate.endpoint_contract_id
        or item.condition.endpoint_contract_hash
        != candidate.endpoint_contract_hash
        for item in run.result_conditions
    ):
        raise ValueError("dual-cohort result endpoint does not match candidate")
    if run.supplemental_condition is not None and (
        run.supplemental_condition.seed_partition_id
        != candidate.supplemental_canonical_seed_partition_id
        or run.supplemental_condition.condition.endpoint_contract_id
        != candidate.endpoint_contract_id
    ):
        raise ValueError("dual-cohort supplemental condition does not match candidate")
    planned_conditions = len(_expected_phase_d_category_ids(run.experiment)) + 1
    logical_budget = (
        planned_conditions * DUAL_COHORT_PHASE_D_MAX_PAGES_PER_CONDITION
    )
    if (
        run.logical_requests > logical_budget
        or run.physical_attempts
        > logical_budget * DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE
    ):
        raise ValueError("complete dual-cohort request budget exceeded")
    candidate_payload = candidate.to_payload()
    run_payload = run.to_payload()
    return {
        "schema_version": 1,
        "experiment": run.experiment,
        "candidate_projection": candidate_payload,
        "candidate_hash": candidate.candidate_hash,
        "candidate_artifact_hash": run.candidate_artifact_hash,
        "baseline": baseline.to_payload(),
        "run": run_payload,
        "run_hash": canonical_dual_cohort_hash(run_payload),
        "accepted": run.accepted,
        "downstream_eligible": run.accepted,
    }


def validate_dual_cohort_phase_d_run_artifact_payload_v3(
    payload: Any,
) -> tuple[
    DualCohortPhaseDRunV3,
    DualCohortDiscoveryPolicyCandidateV3,
    PhaseCBaselineReference,
]:
    expected = {
        "schema_version",
        "experiment",
        "candidate_projection",
        "candidate_hash",
        "candidate_artifact_hash",
        "baseline",
        "run",
        "run_hash",
        "accepted",
        "downstream_eligible",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("complete dual-cohort run artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"]
        not in {
            DUAL_COHORT_CENSUS_EXPERIMENT,
            DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
        }
    ):
        raise ValueError("complete dual-cohort run artifact does not match v3")
    candidate = DualCohortDiscoveryPolicyCandidateV3.from_payload(
        payload["candidate_projection"]
    )
    baseline = PhaseCBaselineReference.from_payload(payload["baseline"])
    run = DualCohortPhaseDRunV3.from_payload(payload["run"])
    expected_payload = dual_cohort_phase_d_run_artifact_payload_v3(
        run=run,
        candidate=candidate,
        baseline=baseline,
    )
    if dict(payload) != expected_payload:
        raise ValueError("complete dual-cohort run artifact does not replay")
    return run, candidate, baseline


@dataclass(frozen=True, slots=True)
class DualCohortPhaseDDecisionV3:
    accepted: bool
    failing_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be an exact boolean")
        if self.accepted != (not self.failing_gates):
            raise ValueError("dual-cohort Phase D decision does not match gates")

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "failing_gates": list(self.failing_gates),
        }


@dataclass(frozen=True, slots=True)
class DualCohortPhaseDStabilityComparisonV3:
    candidate_hash: str
    census_window_span_seconds: float
    fixed_window_span_seconds: float
    result_fixed_min_jaccard: float
    supplemental_fixed_min_jaccard: float
    combined_fixed_min_jaccard: float
    combined_unique_counts: tuple[int, ...]
    combined_unique_count_cv: float
    diagnostic_result_union_ids: tuple[str, ...]
    diagnostic_supplemental_union_ids: tuple[str, ...]
    diagnostic_combined_union_ids: tuple[str, ...]
    stable_result_ids: tuple[str, ...]
    stable_supplemental_ids: tuple[str, ...]
    stable_cohort_overlap_ids: tuple[str, ...]
    stable_reference_ids: tuple[str, ...]
    decision: DualCohortPhaseDDecisionV3

    def __post_init__(self) -> None:
        _sha256(self.candidate_hash, "candidate_hash")
        _finite_nonnegative(
            self.census_window_span_seconds,
            "census_window_span_seconds",
        )
        _finite_nonnegative(
            self.fixed_window_span_seconds,
            "fixed_window_span_seconds",
        )
        for field_name in (
            "result_fixed_min_jaccard",
            "supplemental_fixed_min_jaccard",
            "combined_fixed_min_jaccard",
        ):
            _finite_ratio(getattr(self, field_name), field_name)
        _finite_nonnegative(
            self.combined_unique_count_cv,
            "combined_unique_count_cv",
        )
        if any(type(value) is not int or value < 0 for value in self.combined_unique_counts):
            raise ValueError("combined_unique_counts must be nonnegative integers")
        for field_name in (
            "diagnostic_result_union_ids",
            "diagnostic_supplemental_union_ids",
            "diagnostic_combined_union_ids",
            "stable_result_ids",
            "stable_supplemental_ids",
            "stable_cohort_overlap_ids",
            "stable_reference_ids",
        ):
            values = getattr(self, field_name)
            if values != _canonical_ids(values):
                raise ValueError(f"{field_name} must be canonical")
        if self.diagnostic_combined_union_ids != _canonical_ids(
            (
                *self.diagnostic_result_union_ids,
                *self.diagnostic_supplemental_union_ids,
            )
        ):
            raise ValueError("diagnostic combined union does not match cohorts")
        if self.stable_cohort_overlap_ids != tuple(
            sorted(set(self.stable_result_ids) & set(self.stable_supplemental_ids))
        ):
            raise ValueError("stable cohort overlap does not match")
        if self.stable_reference_ids != _canonical_ids(
            (*self.stable_result_ids, *self.stable_supplemental_ids)
        ):
            raise ValueError("stable reference does not match both cohorts")

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_hash": self.candidate_hash,
            "census_window_span_seconds": self.census_window_span_seconds,
            "fixed_window_span_seconds": self.fixed_window_span_seconds,
            "result_fixed_min_jaccard": self.result_fixed_min_jaccard,
            "supplemental_fixed_min_jaccard": (
                self.supplemental_fixed_min_jaccard
            ),
            "combined_fixed_min_jaccard": self.combined_fixed_min_jaccard,
            "combined_unique_counts": list(self.combined_unique_counts),
            "combined_unique_count_cv": self.combined_unique_count_cv,
            "diagnostic_result_union_ids": list(
                self.diagnostic_result_union_ids
            ),
            "diagnostic_result_union_hash": phase_d_id_set_hash(
                self.diagnostic_result_union_ids
            ),
            "diagnostic_supplemental_union_ids": list(
                self.diagnostic_supplemental_union_ids
            ),
            "diagnostic_supplemental_union_hash": phase_d_id_set_hash(
                self.diagnostic_supplemental_union_ids
            ),
            "diagnostic_combined_union_ids": list(
                self.diagnostic_combined_union_ids
            ),
            "diagnostic_combined_union_hash": phase_d_id_set_hash(
                self.diagnostic_combined_union_ids
            ),
            "stable_result_ids": list(self.stable_result_ids),
            "stable_result_hash": phase_d_id_set_hash(self.stable_result_ids),
            "stable_supplemental_ids": list(self.stable_supplemental_ids),
            "stable_supplemental_hash": phase_d_id_set_hash(
                self.stable_supplemental_ids
            ),
            "stable_cohort_overlap_ids": list(
                self.stable_cohort_overlap_ids
            ),
            "stable_cohort_overlap_hash": phase_d_id_set_hash(
                self.stable_cohort_overlap_ids
            ),
            "stable_reference_ids": list(self.stable_reference_ids),
            "stable_reference_hash": phase_d_id_set_hash(
                self.stable_reference_ids
            ),
            "decision": self.decision.to_payload(),
        }


def _stable_ids_by_frequency(
    cohorts: Sequence[Iterable[str]],
) -> tuple[str, ...]:
    frequency: dict[str, int] = {}
    for cohort in cohorts:
        for job_id in set(cohort):
            frequency[job_id] = frequency.get(job_id, 0) + 1
    return _canonical_ids(
        job_id for job_id, count in frequency.items() if count >= 2
    )


def compare_dual_cohort_phase_d_runs_v3(
    census_runs: Sequence[DualCohortPhaseDRunV3],
    fixed_runs: Sequence[DualCohortPhaseDRunV3],
) -> DualCohortPhaseDStabilityComparisonV3:
    censuses = tuple(census_runs)
    fixed = tuple(fixed_runs)
    if len(censuses) != 3 or len(fixed) != 3:
        raise ValueError("dual-cohort comparison requires three census and fixed runs")
    if any(run.experiment != DUAL_COHORT_CENSUS_EXPERIMENT for run in censuses):
        raise ValueError("dual-cohort census parent experiment does not match")
    if any(
        run.experiment != DUAL_COHORT_FIXED_REPEAT_EXPERIMENT for run in fixed
    ):
        raise ValueError("dual-cohort fixed parent experiment does not match")
    if tuple(run.run_index for run in censuses) != (1, 2, 3):
        raise ValueError("dual-cohort census indexes must be 1, 2, 3")
    if tuple(run.run_index for run in fixed) != (1, 2, 3):
        raise ValueError("dual-cohort fixed indexes must be 1, 2, 3")
    all_runs = (*censuses, *fixed)
    if len({run.run_id for run in all_runs}) != 6:
        raise ValueError("dual-cohort parent run IDs must be distinct")
    if len({run.candidate_hash for run in all_runs}) != 1:
        raise ValueError("dual-cohort parents must share one candidate")
    if len({run.candidate_artifact_hash for run in all_runs}) != 1:
        raise ValueError("dual-cohort parents must share one candidate artifact")

    census_times = tuple(_aware_datetime(run.captured_at, "captured_at") for run in censuses)
    fixed_times = tuple(_aware_datetime(run.captured_at, "captured_at") for run in fixed)
    census_span = (max(census_times) - min(census_times)).total_seconds()
    fixed_span = (max(fixed_times) - min(fixed_times)).total_seconds()
    census_window_count = len({run.window_id for run in censuses})
    fixed_window_count = len({run.window_id for run in fixed})

    result_fixed_jaccard = _minimum_pairwise_jaccard(
        tuple(run.result_job_ids for run in fixed)
    )
    supplemental_fixed_jaccard = _minimum_pairwise_jaccard(
        tuple(run.supplemental_job_ids for run in fixed)
    )
    combined_fixed_jaccard = _minimum_pairwise_jaccard(
        tuple(run.combined_job_ids for run in fixed)
    )
    combined_counts = tuple(len(run.combined_job_ids) for run in censuses)
    combined_mean = statistics.fmean(combined_counts)
    combined_cv = (
        statistics.pstdev(combined_counts) / combined_mean
        if combined_mean
        else 0.0
    )

    diagnostic_result = _canonical_ids(
        job_id for run in censuses for job_id in run.result_job_ids
    )
    diagnostic_supplemental = _canonical_ids(
        job_id for run in censuses for job_id in run.supplemental_job_ids
    )
    stable_result = _stable_ids_by_frequency(
        tuple(run.result_job_ids for run in censuses)
    )
    stable_supplemental = _stable_ids_by_frequency(
        tuple(run.supplemental_job_ids for run in censuses)
    )
    stable_overlap = tuple(
        sorted(set(stable_result) & set(stable_supplemental))
    )
    stable_reference = _canonical_ids((*stable_result, *stable_supplemental))

    failing_gates: list[str] = []
    if not all(run.accepted for run in censuses):
        failing_gates.append("all_three_censuses_accepted")
    if not all(run.accepted for run in fixed):
        failing_gates.append("all_three_fixed_repeats_accepted")
    if (
        census_window_count < 2
        or census_span < DUAL_COHORT_CENSUS_MIN_WINDOW_SECONDS
    ):
        failing_gates.append("census_window_separation")
    if (
        fixed_window_count != 1
        or fixed_span > DUAL_COHORT_FIXED_MAX_WINDOW_SECONDS
    ):
        failing_gates.append("fixed_short_window")
    for field_name, value in (
        ("result_fixed_cohort_jaccard", result_fixed_jaccard),
        ("supplemental_fixed_cohort_jaccard", supplemental_fixed_jaccard),
        ("combined_fixed_cohort_jaccard", combined_fixed_jaccard),
    ):
        if value < 0.95:
            failing_gates.append(field_name)
    if combined_cv > 0.05:
        failing_gates.append("combined_unique_count_cv")
    if not stable_result:
        failing_gates.append("nonempty_stable_result_cohort")
    if not stable_supplemental:
        failing_gates.append("nonempty_stable_supplemental_cohort")

    return DualCohortPhaseDStabilityComparisonV3(
        candidate_hash=censuses[0].candidate_hash,
        census_window_span_seconds=census_span,
        fixed_window_span_seconds=fixed_span,
        result_fixed_min_jaccard=result_fixed_jaccard,
        supplemental_fixed_min_jaccard=supplemental_fixed_jaccard,
        combined_fixed_min_jaccard=combined_fixed_jaccard,
        combined_unique_counts=combined_counts,
        combined_unique_count_cv=combined_cv,
        diagnostic_result_union_ids=diagnostic_result,
        diagnostic_supplemental_union_ids=diagnostic_supplemental,
        diagnostic_combined_union_ids=_canonical_ids(
            (*diagnostic_result, *diagnostic_supplemental)
        ),
        stable_result_ids=stable_result,
        stable_supplemental_ids=stable_supplemental,
        stable_cohort_overlap_ids=stable_overlap,
        stable_reference_ids=stable_reference,
        decision=DualCohortPhaseDDecisionV3(
            accepted=not failing_gates,
            failing_gates=tuple(failing_gates),
        ),
    )


def dual_cohort_phase_d_comparison_payload_v3(
    census_runs: Sequence[DualCohortPhaseDRunV3],
    fixed_runs: Sequence[DualCohortPhaseDRunV3],
) -> dict[str, Any]:
    censuses = tuple(census_runs)
    fixed = tuple(fixed_runs)
    comparison = compare_dual_cohort_phase_d_runs_v3(censuses, fixed)
    inputs = {
        "census_runs": [run.to_payload() for run in censuses],
        "fixed_runs": [run.to_payload() for run in fixed],
    }
    comparison_payload = comparison.to_payload()
    return {
        "schema_version": 1,
        "experiment": DUAL_COHORT_COMPARISON_EXPERIMENT,
        "inputs": inputs,
        "input_set_hash": canonical_dual_cohort_hash(inputs),
        "comparison": comparison_payload,
        "comparison_hash": canonical_dual_cohort_hash(comparison_payload),
        "stable_reference_frozen": comparison.decision.accepted,
        "downstream_eligible": comparison.decision.accepted,
    }


def validate_dual_cohort_phase_d_comparison_payload_v3(
    payload: Any,
) -> DualCohortPhaseDStabilityComparisonV3:
    expected = {
        "schema_version",
        "experiment",
        "inputs",
        "input_set_hash",
        "comparison",
        "comparison_hash",
        "stable_reference_frozen",
        "downstream_eligible",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("dual-cohort Phase D comparison fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != DUAL_COHORT_COMPARISON_EXPERIMENT
    ):
        raise ValueError("dual-cohort Phase D comparison does not match v3")
    inputs = payload["inputs"]
    if (
        not isinstance(inputs, Mapping)
        or set(inputs) != {"census_runs", "fixed_runs"}
        or not isinstance(inputs["census_runs"], list)
        or not isinstance(inputs["fixed_runs"], list)
    ):
        raise ValueError("dual-cohort Phase D comparison inputs do not match")
    censuses = tuple(
        DualCohortPhaseDRunV3.from_payload(item)
        for item in inputs["census_runs"]
    )
    fixed = tuple(
        DualCohortPhaseDRunV3.from_payload(item)
        for item in inputs["fixed_runs"]
    )
    comparison = compare_dual_cohort_phase_d_runs_v3(censuses, fixed)
    expected_payload = dual_cohort_phase_d_comparison_payload_v3(
        censuses,
        fixed,
    )
    if dict(payload) != expected_payload:
        raise ValueError("dual-cohort Phase D comparison does not replay")
    return comparison
