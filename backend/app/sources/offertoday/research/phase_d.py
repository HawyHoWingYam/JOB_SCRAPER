"""Pure contracts and decisions for cursor-correct Phase D research.

This module owns no filesystem, database, browser, or CLI dependency.  It is
the single typed boundary between strict Phase C evidence and the additive
Phase D artifact schemas.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any, Iterable, Literal, Mapping, Sequence
from uuid import UUID

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingPageEvidenceV2,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.listing_runner import ListingRunResult
from app.sources.offertoday.research.live_contracts import (
    DiscoveryPolicyCandidateV2,
)
from app.sources.offertoday.research.partition_research import (
    PhaseCConditionEvidence,
    canonical_phase_c_hash,
    offertoday_partition,
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
    validate_comparison_payload,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCBaselineReference,
)


DISCOVERY_POLICY_CANDIDATE_EXPERIMENT = "discovery-policy-candidate-v2"
PHASE_D_CENSUS_EXPERIMENT = "cursor-full-census-v2"
PHASE_D_FIXED_REPEAT_EXPERIMENT = "cursor-fixed-repeat-v2"
PHASE_D_COMPARISON_EXPERIMENT = "cursor-census-stability-comparison-v2"
PHASE_D_CENSUS_MIN_WINDOW_SECONDS = 21_600.0
PHASE_D_FIXED_MAX_WINDOW_SECONDS = 3_600.0
PHASE_D_FIXED_CATEGORY_IDS = (118000, 112000, 127000)
_SHA256_LENGTH = 64


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


def _optional_sha256(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field_name)


def _exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(
            f"{field_name} must be an exact integer >= {minimum}"
        )
    return value


def _finite_nonnegative(value: Any, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a finite nonnegative number")
    return float(value)


def _aware_datetime(value: str, field_name: str) -> datetime:
    _nonblank(value, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


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


def phase_d_id_set_hash(values: Iterable[str]) -> str:
    canonical = json.dumps(
        list(_canonical_ids(values)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _retained_conditions(
    comparison_payload: Mapping[str, Any],
) -> tuple[PhaseCConditionEvidence, ...]:
    decision = validate_comparison_payload(comparison_payload)
    if not decision.accepted:
        raise ValueError("Phase C comparison did not retain a discovery condition")

    inputs = tuple(
        PhaseCConditionEvidence.from_payload(item)
        for item in comparison_payload["inputs"]
    )
    by_partition = {condition.partition_id: condition for condition in inputs}
    retained_ids = tuple(
        contribution.partition_id
        for contribution in decision.contributions
        if contribution.retained
    )
    if not retained_ids:
        raise ValueError("Phase C comparison retained set is empty")
    retained = tuple(by_partition[partition_id] for partition_id in retained_ids)
    for condition in retained:
        if not (
            condition.contract_verified
            and condition.terminal_confirmed
            and condition.empty_confirmation
            and condition.is_complete
            and condition.stop_reason == "natural_exhaustion"
            and condition.gap_count == 0
            and condition.identity_conflict_count == 0
            and condition.identity_issue_count == 0
            and condition.conservation_difference == 0
        ):
            raise ValueError(
                "retained Phase C condition does not satisfy the policy freeze gate"
            )
    return retained


def build_discovery_policy_candidate_v2(
    *,
    comparison_payload: Mapping[str, Any],
    endpoint_contract_id: str,
    phase_b_comparison_artifact_hash: str,
    phase_c_comparison_artifact_hash: str,
) -> DiscoveryPolicyCandidateV2:
    """Build the immutable Phase D predecessor from strict Phase C evidence.

    The caller owns generic/strict artifact loading and lineage checks.  This
    pure layer reconstructs all semantic values and accepts no policy override.
    """

    if not isinstance(comparison_payload, Mapping):
        raise ValueError("Phase C comparison payload must be a mapping")
    retained = _retained_conditions(comparison_payload)
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    if not contract.cursor_verified or not contract.terminal_verified:
        raise ValueError("Phase D requires a verified cursor/terminal contract")
    if any(
        condition.endpoint_contract_id != contract.contract_id
        or condition.endpoint_contract_hash != contract.contract_hash
        for condition in retained
    ):
        raise ValueError("retained Phase C conditions use a different endpoint")

    return DiscoveryPolicyCandidateV2(
        candidate_version=2,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        endpoint=contract.endpoint,
        rcd_type=None,
        category_catalog_version=OFFERTODAY_CATEGORY_CATALOG_VERSION,
        category_catalog_hash=offertoday_category_catalog_hash(),
        partition_catalog_hash=offertoday_partition_catalog_hash(),
        phase_d_partitions=tuple(
            top_level_partition(category.code)
            for category in OFFERTODAY_CATEGORIES_L1
        ),
        retained_partition_ids=tuple(
            condition.partition_id for condition in retained
        ),
        retained_condition_hashes=tuple(
            canonical_phase_c_hash(condition.to_payload())
            for condition in retained
        ),
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="condition-local-runtime",
        request_policy_hash=phase_c_request_policy_hash(contract.contract_id),
        terminal_policy="cursor-terminal-empty-confirmation-v1",
        max_pages_per_condition=500,
        require_empty_confirmation=True,
        max_attempts_per_page=3,
        retry_delays_seconds=(5.0, 15.0),
        page_delay_range_seconds=(3.0, 5.0),
        session_mode="saved-session",
        fixed_repeat_category_ids=(118000, 112000, 127000),
        phase_b_comparison_artifact_hash=phase_b_comparison_artifact_hash,
        phase_c_comparison_artifact_hash=phase_c_comparison_artifact_hash,
        source_artifact_hash=canonical_phase_c_hash(dict(comparison_payload)),
        deferred_issue_ids=(4, 5),
    )


def discovery_policy_candidate_artifact_payload(
    candidate: DiscoveryPolicyCandidateV2,
) -> dict[str, Any]:
    candidate_payload = candidate.to_payload()
    return {
        "schema_version": 1,
        "experiment": DISCOVERY_POLICY_CANDIDATE_EXPERIMENT,
        "candidate": candidate_payload,
        "candidate_hash": candidate.candidate_hash,
        "phase_b_comparison_artifact_hash": (
            candidate.phase_b_comparison_artifact_hash
        ),
        "phase_c_comparison_artifact_hash": (
            candidate.phase_c_comparison_artifact_hash
        ),
        "source_artifact_hash": candidate.source_artifact_hash,
        "candidate_frozen": True,
    }


def validate_discovery_policy_candidate_artifact_payload(
    payload: Any,
) -> DiscoveryPolicyCandidateV2:
    expected = {
        "schema_version",
        "experiment",
        "candidate",
        "candidate_hash",
        "phase_b_comparison_artifact_hash",
        "phase_c_comparison_artifact_hash",
        "source_artifact_hash",
        "candidate_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("discovery policy artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != DISCOVERY_POLICY_CANDIDATE_EXPERIMENT
        or payload["candidate_frozen"] is not True
    ):
        raise ValueError("discovery policy artifact contract does not match v2")
    candidate = DiscoveryPolicyCandidateV2.from_payload(payload["candidate"])
    expected_payload = discovery_policy_candidate_artifact_payload(candidate)
    if dict(payload) != expected_payload:
        raise ValueError("discovery policy artifact does not replay")
    return candidate


@dataclass(frozen=True, slots=True)
class PhaseDPageCursorEvidence:
    """Secret-safe projection of v2 page evidence for durable artifacts."""

    protocol_version: int
    variant_id: str
    repeat_index: int
    condition_restart_index: int
    condition_execution_id: str
    logical_request_id: str
    physical_attempt_id: str
    browser_context_hash: str | None
    pagination_mode: str
    browser_lifecycle: str
    requested_page_size: int
    response_page_size: int | None
    effective_page_size: int | None
    cursor_input_hash: str | None
    cursor_output_hash: str | None
    session_input_hash: str | None
    session_output_hash: str | None
    cursor_fields_complete: bool
    session_continuity: str
    result_row_count: int
    supplemental_row_count: int
    result_job_ids: tuple[str, ...]
    supplemental_job_ids: tuple[str, ...]
    cohort_overlap_job_ids: tuple[str, ...]
    new_job_id_count: int
    duplicate_job_id_count: int
    zero_new_full_page: bool
    terminal_signal: bool
    awaiting_empty_confirmation: bool
    contract_error: str | None

    def __post_init__(self) -> None:
        if self.protocol_version != 2:
            raise ValueError("Phase D page protocol_version must equal 2")
        _nonblank(self.variant_id, "variant_id")
        if type(self.repeat_index) is not int or self.repeat_index not in (1, 2):
            raise ValueError("repeat_index must be 1 or 2")
        _exact_int(
            self.condition_restart_index,
            "condition_restart_index",
        )
        for field_name in (
            "condition_execution_id",
            "logical_request_id",
            "physical_attempt_id",
        ):
            _sha256(getattr(self, field_name), field_name)
        _optional_sha256(self.browser_context_hash, "browser_context_hash")
        if self.pagination_mode != "response-cursor":
            raise ValueError("Phase D page must use response-cursor pagination")
        if self.browser_lifecycle != "condition-local-runtime":
            raise ValueError("Phase D page must use condition-local runtime")
        _exact_int(self.requested_page_size, "requested_page_size", minimum=1)
        if self.response_page_size is not None:
            _exact_int(self.response_page_size, "response_page_size", minimum=1)
        if self.effective_page_size is not None:
            _exact_int(self.effective_page_size, "effective_page_size", minimum=1)
        for field_name in (
            "cursor_input_hash",
            "cursor_output_hash",
            "session_input_hash",
            "session_output_hash",
        ):
            _optional_sha256(getattr(self, field_name), field_name)
        if type(self.cursor_fields_complete) is not bool:
            raise ValueError("cursor_fields_complete must be an exact boolean")
        if self.session_continuity not in {
            "initial",
            "continued",
            "violation",
            "unavailable",
        }:
            raise ValueError("unsupported Phase D session continuity")
        for field_name in (
            "result_row_count",
            "supplemental_row_count",
            "new_job_id_count",
            "duplicate_job_id_count",
        ):
            _exact_int(getattr(self, field_name), field_name)
        for field_name in (
            "result_job_ids",
            "supplemental_job_ids",
            "cohort_overlap_job_ids",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                for value in values
            ):
                raise ValueError(f"{field_name} must contain exact IDs")
        if tuple(
            sorted(set(self.result_job_ids) & set(self.supplemental_job_ids))
        ) != self.cohort_overlap_job_ids:
            raise ValueError("Phase D page cohort overlap does not match")
        for field_name in (
            "zero_new_full_page",
            "terminal_signal",
            "awaiting_empty_confirmation",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be an exact boolean")
        if self.contract_error is not None:
            _nonblank(self.contract_error, "contract_error")

    @classmethod
    def from_listing_page_evidence(
        cls,
        value: OfferTodayListingPageEvidenceV2,
    ) -> "PhaseDPageCursorEvidence":
        cursor_fields = value.response_cursor_fields
        cursor_input = value.cursor_input
        cursor_output = value.cursor_output
        return cls(
            protocol_version=value.protocol_version,
            variant_id=value.variant_id,
            repeat_index=value.repeat_index,
            condition_restart_index=value.condition_restart_index,
            condition_execution_id=value.condition_execution_id,
            logical_request_id=value.logical_request_id,
            physical_attempt_id=value.physical_attempt_id,
            browser_context_hash=value.browser_context_hash,
            pagination_mode=value.pagination_mode,
            browser_lifecycle=value.browser_lifecycle,
            requested_page_size=value.requested_page_size,
            response_page_size=value.response_page_size,
            effective_page_size=value.effective_page_size,
            cursor_input_hash=(
                cursor_input.cursor_hash if cursor_input is not None else None
            ),
            cursor_output_hash=(
                cursor_output.cursor_hash if cursor_output is not None else None
            ),
            session_input_hash=(
                cursor_input.session_id_hash if cursor_input is not None else None
            ),
            session_output_hash=(
                cursor_output.session_id_hash if cursor_output is not None else None
            ),
            cursor_fields_complete=(
                cursor_fields.session_id
                and cursor_fields.supple_page
                and cursor_fields.supple_amount
                and cursor_fields.supple_type
                and cursor_fields.page_size
            ),
            session_continuity=value.session_continuity,
            result_row_count=value.result_row_count,
            supplemental_row_count=value.supplemental_row_count,
            result_job_ids=value.result_job_ids,
            supplemental_job_ids=value.supplemental_job_ids,
            cohort_overlap_job_ids=value.cohort_overlap_job_ids,
            new_job_id_count=value.new_job_id_count,
            duplicate_job_id_count=value.duplicate_job_id_count,
            zero_new_full_page=value.zero_new_full_page,
            terminal_signal=value.terminal_signal,
            awaiting_empty_confirmation=value.awaiting_empty_confirmation,
            contract_error=value.contract_error,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            field_name: (
                list(value) if isinstance(value, tuple) else value
            )
            for field_name in self.__dataclass_fields__
            for value in (getattr(self, field_name),)
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDPageCursorEvidence":
        expected = set(cls.__dataclass_fields__)
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase D cursor evidence fields do not match")
        values = dict(payload)
        for field_name in (
            "result_job_ids",
            "supplemental_job_ids",
            "cohort_overlap_job_ids",
        ):
            if not isinstance(values[field_name], list):
                raise ValueError(f"{field_name} must be a list")
            values[field_name] = tuple(values[field_name])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class PhaseDPageAttempt:
    condition_id: str
    category_id: int
    page: int
    attempt: int
    request_fingerprint: str
    classification: str
    retry_reason: str | None
    stop_reason: str | None
    cursor_evidence: PhaseDPageCursorEvidence

    def __post_init__(self) -> None:
        _sha256(self.condition_id, "condition_id")
        _exact_int(self.category_id, "category_id", minimum=1)
        _exact_int(self.page, "page", minimum=1)
        _exact_int(self.attempt, "attempt", minimum=1)
        _sha256(self.request_fingerprint, "request_fingerprint")
        _nonblank(self.classification, "classification")
        if self.retry_reason is not None:
            _nonblank(self.retry_reason, "retry_reason")
        if self.stop_reason is not None:
            _nonblank(self.stop_reason, "stop_reason")
        evidence = self.cursor_evidence
        if evidence.requested_page_size != 10:
            raise ValueError("Phase D page requested_page_size must equal 10")

    @property
    def job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            (
                *self.cursor_evidence.result_job_ids,
                *self.cursor_evidence.supplemental_job_ids,
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "category_id": self.category_id,
            "page": self.page,
            "attempt": self.attempt,
            "request_fingerprint": self.request_fingerprint,
            "classification": self.classification,
            "retry_reason": self.retry_reason,
            "stop_reason": self.stop_reason,
            "cursor_evidence": self.cursor_evidence.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDPageAttempt":
        expected = {
            "condition_id",
            "category_id",
            "page",
            "attempt",
            "request_fingerprint",
            "classification",
            "retry_reason",
            "stop_reason",
            "cursor_evidence",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase D page attempt fields do not match")
        return cls(
            condition_id=payload["condition_id"],
            category_id=payload["category_id"],
            page=payload["page"],
            attempt=payload["attempt"],
            request_fingerprint=payload["request_fingerprint"],
            classification=payload["classification"],
            retry_reason=payload["retry_reason"],
            stop_reason=payload["stop_reason"],
            cursor_evidence=PhaseDPageCursorEvidence.from_payload(
                payload["cursor_evidence"]
            ),
        )


@dataclass(frozen=True, slots=True)
class PhaseDZeroNewFullPage:
    logical_request_id: str
    page: int
    condition_restart_index: int
    result_row_count: int
    supplemental_row_count: int
    classification: str | None

    @property
    def classified(self) -> bool:
        return self.classification is not None

    def to_payload(self) -> dict[str, Any]:
        return {
            "logical_request_id": self.logical_request_id,
            "page": self.page,
            "condition_restart_index": self.condition_restart_index,
            "result_row_count": self.result_row_count,
            "supplemental_row_count": self.supplemental_row_count,
            "classification": self.classification,
            "classified": self.classified,
        }


@dataclass(frozen=True, slots=True)
class PhaseDConditionEvidence:
    partition_id: str
    endpoint_contract_id: str
    endpoint_contract_hash: str
    category_id: int
    condition_id: str
    stop_reason: str
    is_complete: bool
    gap_count: int
    identity_conflict_count: int
    identity_issue_count: int
    conservation_difference: int
    pages: tuple[PhaseDPageAttempt, ...]

    def __post_init__(self) -> None:
        partition = offertoday_partition(self.partition_id)
        if partition.category_code != self.category_id:
            raise ValueError("Phase D partition does not match category_id")
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("Phase D endpoint contract hash does not match")
        if not contract.cursor_verified or not contract.terminal_verified:
            raise ValueError("Phase D condition requires a verified endpoint")
        _sha256(self.condition_id, "condition_id")
        _nonblank(self.stop_reason, "stop_reason")
        if type(self.is_complete) is not bool:
            raise ValueError("is_complete must be an exact boolean")
        for field_name in (
            "gap_count",
            "identity_conflict_count",
            "identity_issue_count",
            "conservation_difference",
        ):
            _exact_int(getattr(self, field_name), field_name)
        if not isinstance(self.pages, tuple):
            raise ValueError("Phase D condition pages must be a tuple")
        if any(
            page.condition_id != self.condition_id
            or page.category_id != self.category_id
            for page in self.pages
        ):
            raise ValueError("Phase D page does not belong to its condition")
        physical_ids = tuple(
            page.cursor_evidence.physical_attempt_id for page in self.pages
        )
        if len(set(physical_ids)) != len(physical_ids):
            raise ValueError("Phase D physical attempt IDs must be distinct")
        retry_inputs: dict[str, set[tuple[str, str | None]]] = {}
        for page in self.pages:
            cursor_input_hash = page.cursor_evidence.cursor_input_hash
            retry_inputs.setdefault(
                page.cursor_evidence.logical_request_id,
                set(),
            ).add((page.request_fingerprint, cursor_input_hash))
        if any(len(values) != 1 for values in retry_inputs.values()):
            raise ValueError("Phase D retry changed its request or input cursor")

    @property
    def job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id for page in self.pages for job_id in page.job_ids
        )

    @property
    def logical_requests(self) -> int:
        return len(
            {
                page.cursor_evidence.logical_request_id
                for page in self.pages
            }
        )

    @property
    def physical_attempts(self) -> int:
        return len(self.pages)

    @property
    def restart_count(self) -> int:
        return max(
            (
                page.cursor_evidence.condition_restart_index
                for page in self.pages
            ),
            default=0,
        )

    @property
    def unexplained_rollover_count(self) -> int:
        return sum(
            page.cursor_evidence.session_continuity == "violation"
            for page in self.pages
        )

    @property
    def cursor_contract_error_count(self) -> int:
        return sum(
            page.cursor_evidence.contract_error is not None
            for page in self.pages
        )

    @property
    def cursor_confirmed_exhaustion(self) -> bool:
        successful = tuple(
            page for page in self.pages if page.classification == "success"
        )
        if not successful:
            return False
        final = successful[-1].cursor_evidence
        return (
            self.is_complete
            and self.stop_reason == "natural_exhaustion"
            and final.terminal_signal
            and final.awaiting_empty_confirmation
            and final.result_row_count == 0
            and final.supplemental_row_count == 0
            and final.contract_error is None
        )

    @property
    def zero_new_full_pages(self) -> tuple[PhaseDZeroNewFullPage, ...]:
        classifications: list[PhaseDZeroNewFullPage] = []
        for index, page in enumerate(self.pages):
            evidence = page.cursor_evidence
            if not evidence.zero_new_full_page:
                continue
            cursor_advances = (
                evidence.cursor_input_hash is not None
                and evidence.cursor_output_hash is not None
                and evidence.cursor_input_hash != evidence.cursor_output_hash
            )
            later_same_chain = any(
                later.classification == "success"
                and later.cursor_evidence.condition_restart_index
                == evidence.condition_restart_index
                for later in self.pages[index + 1 :]
            )
            classification = None
            if (
                page.classification == "success"
                and evidence.contract_error is None
                and evidence.session_continuity == "continued"
                and cursor_advances
                and later_same_chain
                and self.cursor_confirmed_exhaustion
            ):
                classification = (
                    "supplemental-repeat-with-cursor-progress-v1"
                    if evidence.result_row_count == 0
                    and evidence.supplemental_row_count > 0
                    else "recommendation-repeat-with-cursor-progress-v1"
                )
            classifications.append(
                PhaseDZeroNewFullPage(
                    logical_request_id=evidence.logical_request_id,
                    page=page.page,
                    condition_restart_index=evidence.condition_restart_index,
                    result_row_count=evidence.result_row_count,
                    supplemental_row_count=evidence.supplemental_row_count,
                    classification=classification,
                )
            )
        return tuple(classifications)

    @property
    def unclassified_zero_new_full_pages(self) -> int:
        return sum(not page.classified for page in self.zero_new_full_pages)

    @property
    def unclassified_failure_count(self) -> int:
        return sum(
            page.classification != "success"
            and page.retry_reason is None
            and page.stop_reason is None
            for page in self.pages
        )

    @property
    def accepted(self) -> bool:
        return (
            self.cursor_confirmed_exhaustion
            and self.gap_count == 0
            and self.identity_conflict_count == 0
            and self.identity_issue_count == 0
            and self.conservation_difference == 0
            and self.unexplained_rollover_count == 0
            and self.cursor_contract_error_count == 0
            and self.unclassified_zero_new_full_pages == 0
            and self.unclassified_failure_count == 0
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract_hash": self.endpoint_contract_hash,
            "category_id": self.category_id,
            "condition_id": self.condition_id,
            "stop_reason": self.stop_reason,
            "is_complete": self.is_complete,
            "gap_count": self.gap_count,
            "identity_conflict_count": self.identity_conflict_count,
            "identity_issue_count": self.identity_issue_count,
            "conservation_difference": self.conservation_difference,
            "pages": [page.to_payload() for page in self.pages],
            "job_ids": list(self.job_ids),
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "restart_count": self.restart_count,
            "cursor_confirmed_exhaustion": self.cursor_confirmed_exhaustion,
            "unexplained_rollover_count": self.unexplained_rollover_count,
            "cursor_contract_error_count": self.cursor_contract_error_count,
            "zero_new_full_pages": [
                page.to_payload() for page in self.zero_new_full_pages
            ],
            "unclassified_zero_new_full_pages": (
                self.unclassified_zero_new_full_pages
            ),
            "unclassified_failure_count": self.unclassified_failure_count,
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDConditionEvidence":
        base_fields = {
            "partition_id",
            "endpoint_contract_id",
            "endpoint_contract_hash",
            "category_id",
            "condition_id",
            "stop_reason",
            "is_complete",
            "gap_count",
            "identity_conflict_count",
            "identity_issue_count",
            "conservation_difference",
            "pages",
        }
        expected = base_fields | {
            "job_ids",
            "logical_requests",
            "physical_attempts",
            "restart_count",
            "cursor_confirmed_exhaustion",
            "unexplained_rollover_count",
            "cursor_contract_error_count",
            "zero_new_full_pages",
            "unclassified_zero_new_full_pages",
            "unclassified_failure_count",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase D condition evidence fields do not match")
        raw_pages = payload["pages"]
        if not isinstance(raw_pages, list):
            raise ValueError("Phase D condition pages must be a list")
        value = cls(
            partition_id=payload["partition_id"],
            endpoint_contract_id=payload["endpoint_contract_id"],
            endpoint_contract_hash=payload["endpoint_contract_hash"],
            category_id=payload["category_id"],
            condition_id=payload["condition_id"],
            stop_reason=payload["stop_reason"],
            is_complete=payload["is_complete"],
            gap_count=payload["gap_count"],
            identity_conflict_count=payload["identity_conflict_count"],
            identity_issue_count=payload["identity_issue_count"],
            conservation_difference=payload["conservation_difference"],
            pages=tuple(PhaseDPageAttempt.from_payload(item) for item in raw_pages),
        )
        if dict(payload) != value.to_payload():
            raise ValueError("Phase D condition evidence does not replay")
        return value


@dataclass(frozen=True, slots=True)
class PhaseDStagingEvidence:
    staging_mode: Literal["noop", "reconciled"]
    rows_seen: int
    rows_created: int
    published_source_job_ids: tuple[str, ...]
    preexisting_staged_source_job_ids: tuple[str, ...]
    created_source_job_ids: tuple[str, ...]
    deferred_identity_conflict_ids: tuple[str, ...]
    would_stage_rows: int
    stage_calls: int

    def __post_init__(self) -> None:
        if self.staging_mode not in {"noop", "reconciled"}:
            raise ValueError("unsupported Phase D staging mode")
        for field_name in (
            "rows_seen",
            "rows_created",
            "would_stage_rows",
            "stage_calls",
        ):
            _exact_int(getattr(self, field_name), field_name)
        for field_name in (
            "published_source_job_ids",
            "preexisting_staged_source_job_ids",
            "created_source_job_ids",
            "deferred_identity_conflict_ids",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or values != _canonical_ids(values):
                raise ValueError(f"{field_name} must be canonical distinct IDs")
        if self.rows_created != len(self.created_source_job_ids):
            raise ValueError("Phase D staging rows_created amplified canonical IDs")
        if self.staging_mode == "noop" and (
            self.rows_seen != 0
            or self.rows_created != 0
            or self.created_source_job_ids
        ):
            raise ValueError("Phase D no-op staging cannot create or reconcile rows")
        if self.staging_mode == "reconciled" and self.would_stage_rows != 0:
            raise ValueError("reconciled staging cannot report no-op rows")

    @property
    def accepted(self) -> bool:
        return not self.deferred_identity_conflict_ids

    def to_payload(self) -> dict[str, Any]:
        return {
            "staging_mode": self.staging_mode,
            "rows_seen": self.rows_seen,
            "rows_created": self.rows_created,
            "published_source_job_ids": list(self.published_source_job_ids),
            "preexisting_staged_source_job_ids": list(
                self.preexisting_staged_source_job_ids
            ),
            "created_source_job_ids": list(self.created_source_job_ids),
            "deferred_identity_conflict_ids": list(
                self.deferred_identity_conflict_ids
            ),
            "would_stage_rows": self.would_stage_rows,
            "stage_calls": self.stage_calls,
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDStagingEvidence":
        base = {
            "staging_mode",
            "rows_seen",
            "rows_created",
            "published_source_job_ids",
            "preexisting_staged_source_job_ids",
            "created_source_job_ids",
            "deferred_identity_conflict_ids",
            "would_stage_rows",
            "stage_calls",
        }
        if not isinstance(payload, Mapping) or set(payload) != base | {"accepted"}:
            raise ValueError("Phase D staging evidence fields do not match")
        list_fields = (
            "published_source_job_ids",
            "preexisting_staged_source_job_ids",
            "created_source_job_ids",
            "deferred_identity_conflict_ids",
        )
        if any(not isinstance(payload[field], list) for field in list_fields):
            raise ValueError("Phase D staging ID fields must be lists")
        value = cls(
            staging_mode=payload["staging_mode"],
            rows_seen=payload["rows_seen"],
            rows_created=payload["rows_created"],
            published_source_job_ids=tuple(
                payload["published_source_job_ids"]
            ),
            preexisting_staged_source_job_ids=tuple(
                payload["preexisting_staged_source_job_ids"]
            ),
            created_source_job_ids=tuple(payload["created_source_job_ids"]),
            deferred_identity_conflict_ids=tuple(
                payload["deferred_identity_conflict_ids"]
            ),
            would_stage_rows=payload["would_stage_rows"],
            stage_calls=payload["stage_calls"],
        )
        if dict(payload) != value.to_payload():
            raise ValueError("Phase D staging evidence does not replay")
        return value


@dataclass(frozen=True, slots=True)
class PhaseDProductEvidence:
    start_snapshot_hash: str
    end_snapshot_hash: str | None
    start_inventory_hash: str
    end_inventory_hash: str | None
    start_staged_rows_hash: str
    end_staged_rows_hash: str | None
    start_published_jobs_hash: str
    end_published_jobs_hash: str | None
    start_companies_hash: str
    end_companies_hash: str | None
    start_product_data_hash: str
    end_product_data_hash: str | None
    detail_attempts: int
    product_writes: int
    staging: PhaseDStagingEvidence
    activity_evidence_captured: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "start_snapshot_hash",
            "start_inventory_hash",
            "start_staged_rows_hash",
            "start_published_jobs_hash",
            "start_companies_hash",
            "start_product_data_hash",
        ):
            _sha256(getattr(self, field_name), field_name)
        end_fields = (
            "end_snapshot_hash",
            "end_inventory_hash",
            "end_staged_rows_hash",
            "end_published_jobs_hash",
            "end_companies_hash",
            "end_product_data_hash",
        )
        end_values = tuple(getattr(self, field_name) for field_name in end_fields)
        if any(value is None for value in end_values):
            if not all(value is None for value in end_values):
                raise ValueError(
                    "Phase D end product snapshot must be wholly present or absent"
                )
        else:
            for field_name in end_fields:
                _sha256(getattr(self, field_name), field_name)
        _exact_int(self.detail_attempts, "detail_attempts")
        _exact_int(self.product_writes, "product_writes")
        if type(self.activity_evidence_captured) is not bool:
            raise ValueError("activity_evidence_captured must be an exact boolean")

    @property
    def end_snapshot_captured(self) -> bool:
        return self.end_snapshot_hash is not None

    @property
    def jobs_unchanged(self) -> bool:
        return (
            self.end_snapshot_captured
            and self.start_published_jobs_hash == self.end_published_jobs_hash
        )

    @property
    def companies_unchanged(self) -> bool:
        return (
            self.end_snapshot_captured
            and self.start_companies_hash == self.end_companies_hash
        )

    @property
    def accepted(self) -> bool:
        return (
            self.end_snapshot_captured
            and self.activity_evidence_captured
            and self.jobs_unchanged
            and self.companies_unchanged
            and self.detail_attempts == 0
            and self.product_writes == 0
            and self.staging.accepted
            and (
                self.staging.staging_mode == "reconciled"
                or self.start_staged_rows_hash == self.end_staged_rows_hash
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "start_snapshot_hash": self.start_snapshot_hash,
            "end_snapshot_hash": self.end_snapshot_hash,
            "start_inventory_hash": self.start_inventory_hash,
            "end_inventory_hash": self.end_inventory_hash,
            "start_staged_rows_hash": self.start_staged_rows_hash,
            "end_staged_rows_hash": self.end_staged_rows_hash,
            "start_published_jobs_hash": self.start_published_jobs_hash,
            "end_published_jobs_hash": self.end_published_jobs_hash,
            "start_companies_hash": self.start_companies_hash,
            "end_companies_hash": self.end_companies_hash,
            "start_product_data_hash": self.start_product_data_hash,
            "end_product_data_hash": self.end_product_data_hash,
            "detail_attempts": self.detail_attempts,
            "product_writes": self.product_writes,
            "staging": self.staging.to_payload(),
            "activity_evidence_captured": self.activity_evidence_captured,
            "end_snapshot_captured": self.end_snapshot_captured,
            "jobs_unchanged": self.jobs_unchanged,
            "companies_unchanged": self.companies_unchanged,
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDProductEvidence":
        base = {
            "start_snapshot_hash",
            "end_snapshot_hash",
            "start_inventory_hash",
            "end_inventory_hash",
            "start_staged_rows_hash",
            "end_staged_rows_hash",
            "start_published_jobs_hash",
            "end_published_jobs_hash",
            "start_companies_hash",
            "end_companies_hash",
            "start_product_data_hash",
            "end_product_data_hash",
            "detail_attempts",
            "product_writes",
            "staging",
            "activity_evidence_captured",
        }
        expected = base | {
            "end_snapshot_captured",
            "jobs_unchanged",
            "companies_unchanged",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase D product evidence fields do not match")
        value = cls(
            start_snapshot_hash=payload["start_snapshot_hash"],
            end_snapshot_hash=payload["end_snapshot_hash"],
            start_inventory_hash=payload["start_inventory_hash"],
            end_inventory_hash=payload["end_inventory_hash"],
            start_staged_rows_hash=payload["start_staged_rows_hash"],
            end_staged_rows_hash=payload["end_staged_rows_hash"],
            start_published_jobs_hash=payload["start_published_jobs_hash"],
            end_published_jobs_hash=payload["end_published_jobs_hash"],
            start_companies_hash=payload["start_companies_hash"],
            end_companies_hash=payload["end_companies_hash"],
            start_product_data_hash=payload["start_product_data_hash"],
            end_product_data_hash=payload["end_product_data_hash"],
            detail_attempts=payload["detail_attempts"],
            product_writes=payload["product_writes"],
            staging=PhaseDStagingEvidence.from_payload(payload["staging"]),
            activity_evidence_captured=payload["activity_evidence_captured"],
        )
        if dict(payload) != value.to_payload():
            raise ValueError("Phase D product evidence does not replay")
        return value


@dataclass(frozen=True, slots=True)
class PhaseDRunEvidence:
    experiment: Literal["cursor-full-census-v2", "cursor-fixed-repeat-v2"]
    run_id: str
    run_index: int
    window_id: str
    captured_at: str
    candidate_hash: str
    candidate_artifact_hash: str
    duration_seconds: float
    conditions: tuple[PhaseDConditionEvidence, ...]
    detail_attempts: int
    product_writes: int
    jobs_unchanged: bool
    companies_unchanged: bool
    staging_conservation_difference: int
    unclassified_failures: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.experiment not in {
            PHASE_D_CENSUS_EXPERIMENT,
            PHASE_D_FIXED_REPEAT_EXPERIMENT,
        }:
            raise ValueError("unsupported Phase D run experiment")
        try:
            if str(UUID(self.run_id)) != self.run_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("run_id must be a canonical UUID") from exc
        if type(self.run_index) is not int or self.run_index not in (1, 2, 3):
            raise ValueError("run_index must be 1, 2, or 3")
        _nonblank(self.window_id, "window_id")
        _aware_datetime(self.captured_at, "captured_at")
        _sha256(self.candidate_hash, "candidate_hash")
        _sha256(self.candidate_artifact_hash, "candidate_artifact_hash")
        object.__setattr__(
            self,
            "duration_seconds",
            _finite_nonnegative(self.duration_seconds, "duration_seconds"),
        )
        if not isinstance(self.conditions, tuple):
            raise ValueError("Phase D run conditions must be a tuple")
        expected_categories = (
            tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
            if self.experiment == PHASE_D_CENSUS_EXPERIMENT
            else PHASE_D_FIXED_CATEGORY_IDS
        )
        observed_categories = tuple(
            condition.category_id for condition in self.conditions
        )
        if observed_categories != expected_categories[: len(observed_categories)]:
            raise ValueError("Phase D run condition prefix/order does not match")
        if len({condition.condition_id for condition in self.conditions}) != len(
            self.conditions
        ):
            raise ValueError("Phase D condition IDs must be distinct")
        for field_name in (
            "detail_attempts",
            "product_writes",
            "staging_conservation_difference",
            "unclassified_failures",
        ):
            _exact_int(getattr(self, field_name), field_name)
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        expected_unclassified_failures = int(
            isinstance(self.failure_reason, str)
            and self.failure_reason.startswith(
                "unexpected_phase_d_census_error:"
            )
        )
        if self.unclassified_failures != expected_unclassified_failures:
            raise ValueError(
                "Phase D unclassified failure count does not match failure_reason"
            )
        for field_name in ("jobs_unchanged", "companies_unchanged"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be an exact boolean")

    @property
    def captured_datetime(self) -> datetime:
        return _aware_datetime(self.captured_at, "captured_at")

    @property
    def job_ids(self) -> tuple[str, ...]:
        return _canonical_ids(
            job_id for condition in self.conditions for job_id in condition.job_ids
        )

    @property
    def set_hash(self) -> str:
        return phase_d_id_set_hash(self.job_ids)

    @property
    def logical_requests(self) -> int:
        return sum(condition.logical_requests for condition in self.conditions)

    @property
    def physical_attempts(self) -> int:
        return sum(condition.physical_attempts for condition in self.conditions)

    @property
    def unresolved_gaps(self) -> int:
        return sum(condition.gap_count for condition in self.conditions)

    @property
    def identity_conflicts(self) -> int:
        return sum(
            condition.identity_conflict_count for condition in self.conditions
        )

    @property
    def identity_issues(self) -> int:
        return sum(condition.identity_issue_count for condition in self.conditions)

    @property
    def condition_conservation_difference(self) -> int:
        return sum(
            condition.conservation_difference for condition in self.conditions
        )

    @property
    def unexplained_rollovers(self) -> int:
        return sum(
            condition.unexplained_rollover_count for condition in self.conditions
        )

    @property
    def unclassified_zero_new_full_pages(self) -> int:
        return sum(
            condition.unclassified_zero_new_full_pages
            for condition in self.conditions
        )

    @property
    def accepted(self) -> bool:
        expected_condition_count = (
            len(OFFERTODAY_CATEGORIES_L1)
            if self.experiment == PHASE_D_CENSUS_EXPERIMENT
            else len(PHASE_D_FIXED_CATEGORY_IDS)
        )
        return (
            len(self.conditions) == expected_condition_count
            and all(condition.accepted for condition in self.conditions)
            and self.detail_attempts == 0
            and self.product_writes == 0
            and self.jobs_unchanged
            and self.companies_unchanged
            and self.staging_conservation_difference == 0
            and self.unclassified_failures == 0
            and self.failure_reason is None
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "window_id": self.window_id,
            "captured_at": self.captured_at,
            "candidate_hash": self.candidate_hash,
            "candidate_artifact_hash": self.candidate_artifact_hash,
            "duration_seconds": self.duration_seconds,
            "conditions": [condition.to_payload() for condition in self.conditions],
            "planned_condition_count": (
                len(OFFERTODAY_CATEGORIES_L1)
                if self.experiment == PHASE_D_CENSUS_EXPERIMENT
                else len(PHASE_D_FIXED_CATEGORY_IDS)
            ),
            "condition_count": len(self.conditions),
            "job_ids": list(self.job_ids),
            "set_hash": self.set_hash,
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "detail_attempts": self.detail_attempts,
            "product_writes": self.product_writes,
            "jobs_unchanged": self.jobs_unchanged,
            "companies_unchanged": self.companies_unchanged,
            "unresolved_gaps": self.unresolved_gaps,
            "identity_conflicts": self.identity_conflicts,
            "identity_issues": self.identity_issues,
            "condition_conservation_difference": (
                self.condition_conservation_difference
            ),
            "staging_conservation_difference": (
                self.staging_conservation_difference
            ),
            "unclassified_failures": self.unclassified_failures,
            "failure_reason": self.failure_reason,
            "unexplained_rollovers": self.unexplained_rollovers,
            "unclassified_zero_new_full_pages": (
                self.unclassified_zero_new_full_pages
            ),
            "accepted": self.accepted,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseDRunEvidence":
        base_fields = {
            "experiment",
            "run_id",
            "run_index",
            "window_id",
            "captured_at",
            "candidate_hash",
            "candidate_artifact_hash",
            "duration_seconds",
            "conditions",
            "detail_attempts",
            "product_writes",
            "jobs_unchanged",
            "companies_unchanged",
            "staging_conservation_difference",
            "unclassified_failures",
            "failure_reason",
        }
        expected = base_fields | {
            "planned_condition_count",
            "condition_count",
            "job_ids",
            "set_hash",
            "logical_requests",
            "physical_attempts",
            "unresolved_gaps",
            "identity_conflicts",
            "identity_issues",
            "condition_conservation_difference",
            "unexplained_rollovers",
            "unclassified_zero_new_full_pages",
            "accepted",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase D run evidence fields do not match")
        raw_conditions = payload["conditions"]
        if not isinstance(raw_conditions, list):
            raise ValueError("Phase D run conditions must be a list")
        value = cls(
            experiment=payload["experiment"],
            run_id=payload["run_id"],
            run_index=payload["run_index"],
            window_id=payload["window_id"],
            captured_at=payload["captured_at"],
            candidate_hash=payload["candidate_hash"],
            candidate_artifact_hash=payload["candidate_artifact_hash"],
            duration_seconds=payload["duration_seconds"],
            conditions=tuple(
                PhaseDConditionEvidence.from_payload(item)
                for item in raw_conditions
            ),
            detail_attempts=payload["detail_attempts"],
            product_writes=payload["product_writes"],
            jobs_unchanged=payload["jobs_unchanged"],
            companies_unchanged=payload["companies_unchanged"],
            staging_conservation_difference=payload[
                "staging_conservation_difference"
            ],
            unclassified_failures=payload["unclassified_failures"],
            failure_reason=payload["failure_reason"],
        )
        if dict(payload) != value.to_payload():
            raise ValueError("Phase D run evidence does not replay")
        return value


def phase_d_condition_from_listing_result(
    result: ListingRunResult,
    *,
    candidate: DiscoveryPolicyCandidateV2,
    conservation_difference: int = 0,
) -> PhaseDConditionEvidence:
    return phase_d_condition_from_listing_result_contract(
        result,
        endpoint_contract_id=candidate.endpoint_contract_id,
        endpoint=candidate.endpoint,
        rcd_type=candidate.rcd_type,
        conservation_difference=conservation_difference,
    )


def phase_d_condition_from_listing_result_contract(
    result: ListingRunResult,
    *,
    endpoint_contract_id: str,
    endpoint: str,
    rcd_type: int | None,
    partition_id: str | None = None,
    conservation_difference: int = 0,
) -> PhaseDConditionEvidence:
    """Project one cursor run without coupling it to a candidate version."""

    if len(result.condition_outcomes) != 1:
        raise ValueError("Phase D result must own exactly one condition outcome")
    outcome = result.condition_outcomes[0]
    condition = outcome.condition
    if condition.category_id is None:
        raise ValueError("Phase D condition requires category_id")
    if condition.endpoint != endpoint or condition.rcd_type != rcd_type:
        raise ValueError("Phase D condition does not match the candidate endpoint")
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    if contract.endpoint != endpoint or rcd_type not in contract.allowed_rcd_types:
        raise ValueError("Phase D endpoint controls do not match the registry")
    partition = (
        top_level_partition(condition.category_id)
        if partition_id is None
        else offertoday_partition(partition_id)
    )
    if partition.category_code != condition.category_id:
        raise ValueError("Phase D partition does not match the listing condition")
    observations = tuple(
        observation
        for observation in result.observations
        if observation.condition_id == condition.condition_id
    )
    if len(observations) != len(result.observations):
        raise ValueError("Phase D result contains cross-condition observations")
    pages = []
    for observation in observations:
        if observation.cursor_evidence is None:
            raise ValueError("Phase D observation requires v2 cursor evidence")
        pages.append(
            PhaseDPageAttempt(
                condition_id=observation.condition_id,
                category_id=condition.category_id,
                page=observation.page,
                attempt=observation.attempt,
                request_fingerprint=observation.request_fingerprint,
                classification=observation.classification,
                retry_reason=observation.retry_reason,
                stop_reason=observation.stop_reason,
                cursor_evidence=(
                    PhaseDPageCursorEvidence.from_listing_page_evidence(
                        observation.cursor_evidence
                    )
                ),
            )
        )
    return PhaseDConditionEvidence(
        partition_id=partition.partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        category_id=condition.category_id,
        condition_id=condition.condition_id,
        stop_reason=outcome.stop_reason,
        is_complete=outcome.is_complete,
        gap_count=sum(
            gap.condition_id == condition.condition_id for gap in result.gaps
        ),
        identity_conflict_count=len(result.identity_conflicts),
        identity_issue_count=len(result.identity_issues),
        conservation_difference=conservation_difference,
        pages=tuple(pages),
    )


def build_phase_d_run_evidence(
    *,
    experiment: Literal["cursor-full-census-v2", "cursor-fixed-repeat-v2"],
    run_id: str,
    run_index: int,
    window_id: str,
    captured_at: str,
    candidate: DiscoveryPolicyCandidateV2,
    candidate_artifact_hash: str,
    duration_seconds: float,
    results: Sequence[ListingRunResult],
    product: PhaseDProductEvidence,
    failure_reason: str | None,
    condition_conservation_differences: Sequence[int] | None = None,
    staging_conservation_difference: int = 0,
) -> PhaseDRunEvidence:
    result_items = tuple(results)
    differences = (
        tuple(condition_conservation_differences)
        if condition_conservation_differences is not None
        else tuple(0 for _ in result_items)
    )
    if len(differences) != len(result_items):
        raise ValueError("Phase D condition conservation evidence count does not match")
    conditions = tuple(
        phase_d_condition_from_listing_result(
            result,
            candidate=candidate,
            conservation_difference=difference,
        )
        for result, difference in zip(result_items, differences, strict=True)
    )
    unclassified_failures = int(
        isinstance(failure_reason, str)
        and failure_reason.startswith("unexpected_phase_d_census_error:")
    )
    return PhaseDRunEvidence(
        experiment=experiment,
        run_id=run_id,
        run_index=run_index,
        window_id=window_id,
        captured_at=captured_at,
        candidate_hash=candidate.candidate_hash,
        candidate_artifact_hash=candidate_artifact_hash,
        duration_seconds=duration_seconds,
        conditions=conditions,
        detail_attempts=product.detail_attempts,
        product_writes=product.product_writes,
        jobs_unchanged=product.jobs_unchanged,
        companies_unchanged=product.companies_unchanged,
        staging_conservation_difference=staging_conservation_difference,
        unclassified_failures=unclassified_failures,
        failure_reason=failure_reason,
    )


def phase_d_run_artifact_payload(
    *,
    run: PhaseDRunEvidence,
    candidate: DiscoveryPolicyCandidateV2,
    baseline: PhaseCBaselineReference,
    product: PhaseDProductEvidence,
) -> dict[str, Any]:
    if run.candidate_hash != candidate.candidate_hash:
        raise ValueError("Phase D run candidate hash does not match projection")
    if (
        run.detail_attempts != product.detail_attempts
        or run.product_writes != product.product_writes
        or run.jobs_unchanged is not product.jobs_unchanged
        or run.companies_unchanged is not product.companies_unchanged
    ):
        raise ValueError("Phase D run product evidence does not match")
    if (
        baseline.snapshot_hash != product.start_snapshot_hash
        or baseline.inventory_hash != product.start_inventory_hash
    ):
        raise ValueError("Phase D run start state does not match the baseline")
    expected_partition_ids = (
        tuple(partition.partition_id for partition in candidate.phase_d_partitions)
        if run.experiment == PHASE_D_CENSUS_EXPERIMENT
        else tuple(
            top_level_partition(category_id).partition_id
            for category_id in candidate.fixed_repeat_category_ids
        )
    )
    observed_partition_ids = tuple(
        condition.partition_id for condition in run.conditions
    )
    if observed_partition_ids != expected_partition_ids[: len(observed_partition_ids)]:
        raise ValueError("Phase D run partitions do not match the candidate")
    expected_variant_id = f"phase-c:{candidate.endpoint_contract_id}"
    for condition in run.conditions:
        if (
            condition.endpoint_contract_id != candidate.endpoint_contract_id
            or condition.endpoint_contract_hash != candidate.endpoint_contract_hash
        ):
            raise ValueError("Phase D run endpoint does not match the candidate")
        for page in condition.pages:
            evidence = page.cursor_evidence
            if (
                evidence.protocol_version != 2
                or evidence.variant_id != expected_variant_id
                or evidence.repeat_index != 1
                or evidence.pagination_mode != candidate.pagination_mode
                or evidence.requested_page_size != candidate.requested_page_size
                or evidence.browser_lifecycle != candidate.browser_lifecycle
            ):
                raise ValueError("Phase D page controls do not match the candidate")
    logical_budget = len(run.conditions) * candidate.max_pages_per_condition
    if (
        run.logical_requests > logical_budget
        or run.physical_attempts
        > logical_budget * candidate.max_attempts_per_page
    ):
        raise ValueError("Phase D run exceeded the candidate request budget")

    run_payload = run.to_payload()
    candidate_payload = candidate.to_payload()
    product_payload = product.to_payload()
    return {
        "schema_version": 1,
        "experiment": run.experiment,
        "candidate_projection": candidate_payload,
        "candidate_hash": candidate.candidate_hash,
        "candidate_artifact_hash": run.candidate_artifact_hash,
        "baseline": baseline.to_payload(),
        "run": run_payload,
        "run_hash": canonical_phase_c_hash(run_payload),
        "product": product_payload,
        "product_hash": canonical_phase_c_hash(product_payload),
        "accepted": run.accepted and product.accepted,
    }


def validate_phase_d_run_artifact_payload(
    payload: Any,
) -> tuple[
    PhaseDRunEvidence,
    DiscoveryPolicyCandidateV2,
    PhaseCBaselineReference,
    PhaseDProductEvidence,
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
        "product",
        "product_hash",
        "accepted",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("Phase D run artifact fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"]
        not in {PHASE_D_CENSUS_EXPERIMENT, PHASE_D_FIXED_REPEAT_EXPERIMENT}
    ):
        raise ValueError("Phase D run artifact contract does not match v2")
    candidate = DiscoveryPolicyCandidateV2.from_payload(
        payload["candidate_projection"]
    )
    baseline = PhaseCBaselineReference.from_payload(payload["baseline"])
    run = PhaseDRunEvidence.from_payload(payload["run"])
    product = PhaseDProductEvidence.from_payload(payload["product"])
    expected_payload = phase_d_run_artifact_payload(
        run=run,
        candidate=candidate,
        baseline=baseline,
        product=product,
    )
    if dict(payload) != expected_payload:
        raise ValueError("Phase D run artifact does not replay")
    return run, candidate, baseline, product


@dataclass(frozen=True, slots=True)
class PhaseDPairwiseComparison:
    left_run_id: str
    right_run_id: str
    jaccard: float
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "jaccard": self.jaccard,
            "added_ids": list(self.added_ids),
            "removed_ids": list(self.removed_ids),
        }


@dataclass(frozen=True, slots=True)
class PhaseDDecision:
    accepted: bool
    failing_gates: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "failing_gates": list(self.failing_gates),
        }


@dataclass(frozen=True, slots=True)
class PhaseDStabilityComparison:
    candidate_hash: str
    census_window_span_seconds: float
    fixed_window_span_seconds: float
    census_set_hashes: tuple[tuple[str, str], ...]
    fixed_set_hashes: tuple[tuple[str, str], ...]
    census_pairwise: tuple[PhaseDPairwiseComparison, ...]
    fixed_pairwise: tuple[PhaseDPairwiseComparison, ...]
    fixed_cohort_jaccard: float
    census_intersection_ids: tuple[str, ...]
    diagnostic_union_ids: tuple[str, ...]
    stable_reference_ids: tuple[str, ...]
    active_holdout_ids: tuple[str, ...]
    unique_counts: tuple[int, ...]
    unique_count_cv: float
    logical_requests_per_union_id: float
    seconds_per_union_id: float
    unresolved_gaps: int
    identity_conflicts: int
    identity_issues: int
    conservation_difference: int
    unclassified_failures: int
    unexplained_rollovers: int
    unclassified_zero_new_full_pages: int
    decision: PhaseDDecision

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_hash": self.candidate_hash,
            "census_window_span_seconds": self.census_window_span_seconds,
            "fixed_window_span_seconds": self.fixed_window_span_seconds,
            "census_set_hashes": [
                {"run_id": run_id, "set_hash": set_hash}
                for run_id, set_hash in self.census_set_hashes
            ],
            "fixed_set_hashes": [
                {"run_id": run_id, "set_hash": set_hash}
                for run_id, set_hash in self.fixed_set_hashes
            ],
            "census_pairwise": [item.to_payload() for item in self.census_pairwise],
            "fixed_pairwise": [item.to_payload() for item in self.fixed_pairwise],
            "fixed_cohort_jaccard": self.fixed_cohort_jaccard,
            "census_intersection_ids": list(self.census_intersection_ids),
            "census_intersection_hash": phase_d_id_set_hash(
                self.census_intersection_ids
            ),
            "diagnostic_union_ids": list(self.diagnostic_union_ids),
            "diagnostic_union_hash": phase_d_id_set_hash(
                self.diagnostic_union_ids
            ),
            "stable_reference_ids": list(self.stable_reference_ids),
            "stable_reference_hash": phase_d_id_set_hash(
                self.stable_reference_ids
            ),
            "active_holdout_ids": list(self.active_holdout_ids),
            "active_holdout_hash": phase_d_id_set_hash(self.active_holdout_ids),
            "unique_counts": list(self.unique_counts),
            "unique_count_cv": self.unique_count_cv,
            "logical_requests_per_union_id": self.logical_requests_per_union_id,
            "seconds_per_union_id": self.seconds_per_union_id,
            "unresolved_gaps": self.unresolved_gaps,
            "identity_conflicts": self.identity_conflicts,
            "identity_issues": self.identity_issues,
            "conservation_difference": self.conservation_difference,
            "unclassified_failures": self.unclassified_failures,
            "unexplained_rollovers": self.unexplained_rollovers,
            "unclassified_zero_new_full_pages": (
                self.unclassified_zero_new_full_pages
            ),
            "decision": self.decision.to_payload(),
        }


def _pairwise(
    runs: Sequence[PhaseDRunEvidence],
) -> tuple[PhaseDPairwiseComparison, ...]:
    return tuple(
        PhaseDPairwiseComparison(
            left_run_id=left.run_id,
            right_run_id=right.run_id,
            jaccard=(
                len(set(left.job_ids) & set(right.job_ids))
                / len(set(left.job_ids) | set(right.job_ids))
                if set(left.job_ids) | set(right.job_ids)
                else 1.0
            ),
            added_ids=tuple(sorted(set(right.job_ids) - set(left.job_ids))),
            removed_ids=tuple(sorted(set(left.job_ids) - set(right.job_ids))),
        )
        for left, right in combinations(runs, 2)
    )


def _cost_per_id(cost: float, id_count: int) -> float:
    if id_count:
        return cost / id_count
    return 0.0 if cost == 0 else math.inf


def compare_phase_d_runs(
    census_runs: Sequence[PhaseDRunEvidence],
    fixed_runs: Sequence[PhaseDRunEvidence],
    *,
    active_holdout_ids: Iterable[str] = (),
) -> PhaseDStabilityComparison:
    censuses = tuple(census_runs)
    fixed = tuple(fixed_runs)
    if len(censuses) != 3 or len(fixed) != 3:
        raise ValueError("Phase D requires exactly three census and fixed runs")
    if any(run.experiment != PHASE_D_CENSUS_EXPERIMENT for run in censuses):
        raise ValueError("Phase D census parent experiment does not match")
    if any(
        run.experiment != PHASE_D_FIXED_REPEAT_EXPERIMENT for run in fixed
    ):
        raise ValueError("Phase D fixed parent experiment does not match")
    if tuple(run.run_index for run in censuses) != (1, 2, 3):
        raise ValueError("Phase D census run indexes must be 1, 2, 3")
    if tuple(run.run_index for run in fixed) != (1, 2, 3):
        raise ValueError("Phase D fixed run indexes must be 1, 2, 3")
    all_runs = (*censuses, *fixed)
    if len({run.run_id for run in all_runs}) != 6:
        raise ValueError("Phase D parent run IDs must be distinct")
    if len({run.candidate_hash for run in all_runs}) != 1:
        raise ValueError("Phase D parents must share one candidate hash")
    if len({run.candidate_artifact_hash for run in all_runs}) != 1:
        raise ValueError("Phase D parents must share one candidate artifact")

    census_times = tuple(run.captured_datetime for run in censuses)
    fixed_times = tuple(run.captured_datetime for run in fixed)
    census_span = (max(census_times) - min(census_times)).total_seconds()
    fixed_span = (max(fixed_times) - min(fixed_times)).total_seconds()
    census_window_count = len({run.window_id for run in censuses})
    fixed_window_count = len({run.window_id for run in fixed})

    census_pairwise = _pairwise(censuses)
    fixed_pairwise = _pairwise(fixed)
    fixed_jaccard = min(item.jaccard for item in fixed_pairwise)
    census_sets = tuple(set(run.job_ids) for run in censuses)
    diagnostic_union = _canonical_ids(
        job_id for run in censuses for job_id in run.job_ids
    )
    intersection = tuple(sorted(set.intersection(*census_sets)))
    holdouts = _canonical_ids(active_holdout_ids)
    census_frequency: dict[str, int] = {}
    for job_ids in census_sets:
        for job_id in job_ids:
            census_frequency[job_id] = census_frequency.get(job_id, 0) + 1
    stable_reference = _canonical_ids(
        (
            *(
                job_id
                for job_id, count in census_frequency.items()
                if count >= 2
            ),
            *holdouts,
        )
    )
    unique_counts = tuple(len(run.job_ids) for run in censuses)
    mean = statistics.fmean(unique_counts)
    unique_count_cv = (
        statistics.pstdev(unique_counts) / mean
        if mean
        else 0.0
    )
    total_requests = sum(run.logical_requests for run in censuses)
    total_seconds = sum(run.duration_seconds for run in censuses)

    unresolved_gaps = sum(run.unresolved_gaps for run in all_runs)
    identity_conflicts = sum(run.identity_conflicts for run in all_runs)
    identity_issues = sum(run.identity_issues for run in all_runs)
    conservation_difference = sum(
        run.condition_conservation_difference
        + run.staging_conservation_difference
        for run in all_runs
    )
    unclassified_failures = sum(run.unclassified_failures for run in all_runs)
    unexplained_rollovers = sum(run.unexplained_rollovers for run in all_runs)
    unclassified_zero_new = sum(
        run.unclassified_zero_new_full_pages for run in all_runs
    )

    failing_gates: list[str] = []
    if not all(run.accepted for run in censuses):
        failing_gates.append("all_three_censuses_accepted")
    if not all(run.accepted for run in fixed):
        failing_gates.append("all_three_fixed_repeats_accepted")
    if (
        census_window_count < 2
        or census_span < PHASE_D_CENSUS_MIN_WINDOW_SECONDS
    ):
        failing_gates.append("census_window_separation")
    if (
        fixed_window_count != 1
        or fixed_span > PHASE_D_FIXED_MAX_WINDOW_SECONDS
    ):
        failing_gates.append("fixed_short_window")
    if fixed_jaccard < 0.95:
        failing_gates.append("fixed_cohort_jaccard")
    if unique_count_cv > 0.05:
        failing_gates.append("unique_count_cv")
    for field_name, value in (
        ("unresolved_gaps", unresolved_gaps),
        ("identity_conflicts", identity_conflicts),
        ("identity_issues", identity_issues),
        ("conservation_difference", conservation_difference),
        ("unclassified_failures", unclassified_failures),
        ("unexplained_rollovers", unexplained_rollovers),
        ("unclassified_zero_new_full_pages", unclassified_zero_new),
    ):
        if value:
            failing_gates.append(field_name)

    return PhaseDStabilityComparison(
        candidate_hash=censuses[0].candidate_hash,
        census_window_span_seconds=census_span,
        fixed_window_span_seconds=fixed_span,
        census_set_hashes=tuple((run.run_id, run.set_hash) for run in censuses),
        fixed_set_hashes=tuple((run.run_id, run.set_hash) for run in fixed),
        census_pairwise=census_pairwise,
        fixed_pairwise=fixed_pairwise,
        fixed_cohort_jaccard=fixed_jaccard,
        census_intersection_ids=intersection,
        diagnostic_union_ids=diagnostic_union,
        stable_reference_ids=stable_reference,
        active_holdout_ids=holdouts,
        unique_counts=unique_counts,
        unique_count_cv=unique_count_cv,
        logical_requests_per_union_id=_cost_per_id(
            total_requests,
            len(diagnostic_union),
        ),
        seconds_per_union_id=_cost_per_id(
            total_seconds,
            len(diagnostic_union),
        ),
        unresolved_gaps=unresolved_gaps,
        identity_conflicts=identity_conflicts,
        identity_issues=identity_issues,
        conservation_difference=conservation_difference,
        unclassified_failures=unclassified_failures,
        unexplained_rollovers=unexplained_rollovers,
        unclassified_zero_new_full_pages=unclassified_zero_new,
        decision=PhaseDDecision(
            accepted=not failing_gates,
            failing_gates=tuple(failing_gates),
        ),
    )


def phase_d_comparison_payload(
    census_runs: Sequence[PhaseDRunEvidence],
    fixed_runs: Sequence[PhaseDRunEvidence],
    *,
    active_holdout_ids: Iterable[str] = (),
) -> dict[str, Any]:
    censuses = tuple(census_runs)
    fixed = tuple(fixed_runs)
    holdouts = _canonical_ids(active_holdout_ids)
    comparison = compare_phase_d_runs(
        censuses,
        fixed,
        active_holdout_ids=holdouts,
    )
    inputs = {
        "census_runs": [run.to_payload() for run in censuses],
        "fixed_runs": [run.to_payload() for run in fixed],
        "active_holdout_ids": list(holdouts),
    }
    return {
        "schema_version": 1,
        "experiment": PHASE_D_COMPARISON_EXPERIMENT,
        "inputs": inputs,
        "input_set_hash": canonical_phase_c_hash(inputs),
        "comparison": comparison.to_payload(),
        "comparison_hash": canonical_phase_c_hash(comparison.to_payload()),
        "stable_reference_frozen": comparison.decision.accepted,
    }


def validate_phase_d_comparison_payload(
    payload: Any,
) -> PhaseDStabilityComparison:
    expected = {
        "schema_version",
        "experiment",
        "inputs",
        "input_set_hash",
        "comparison",
        "comparison_hash",
        "stable_reference_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("Phase D comparison payload fields do not match")
    if (
        payload["schema_version"] != 1
        or payload["experiment"] != PHASE_D_COMPARISON_EXPERIMENT
    ):
        raise ValueError("Phase D comparison contract does not match v2")
    inputs = payload["inputs"]
    input_fields = {"census_runs", "fixed_runs", "active_holdout_ids"}
    if not isinstance(inputs, Mapping) or set(inputs) != input_fields:
        raise ValueError("Phase D comparison inputs do not match")
    for field_name in input_fields:
        if not isinstance(inputs[field_name], list):
            raise ValueError(f"Phase D comparison {field_name} must be a list")
    censuses = tuple(
        PhaseDRunEvidence.from_payload(item) for item in inputs["census_runs"]
    )
    fixed = tuple(
        PhaseDRunEvidence.from_payload(item) for item in inputs["fixed_runs"]
    )
    comparison = compare_phase_d_runs(
        censuses,
        fixed,
        active_holdout_ids=inputs["active_holdout_ids"],
    )
    expected_payload = phase_d_comparison_payload(
        censuses,
        fixed,
        active_holdout_ids=inputs["active_holdout_ids"],
    )
    if dict(payload) != expected_payload:
        raise ValueError("Phase D comparison does not replay")
    return comparison
