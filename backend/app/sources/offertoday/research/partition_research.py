"""Pure Phase C endpoint and partition research contracts.

This module owns deterministic plans, normalized listing evidence, contribution
metrics, and comparison decisions. It performs no I/O and has no database or
browser dependency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    OfferTodayCategory,
    iter_offertoday_leaf_categories,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import (
    OFFERTODAY_ENDPOINT_CONTRACTS,
    OfferTodayListingEndpointContract,
    OfferTodayListingPageEvidenceV2,
    OfferTodayListingRequestPolicy,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.listing_runner import (
    ListingPageObservation,
    ListingRunResult,
)


PARTITION_SCHEMA_VERSION = 1
ENDPOINT_PROBE_EXPERIMENT = "endpoint-contract-probe-v1"
PARTITION_PROBE_EXPERIMENT = "partition-probe-v1"
PARTITION_COMPARISON_EXPERIMENT = "partition-comparison-v1"
PHASE_C_REQUESTED_PAGE_SIZE = 10
PHASE_C_MAX_ATTEMPTS_PER_PAGE = 3
PHASE_C_RETRY_DELAYS_SECONDS = (5.0, 15.0)
PHASE_C_PAGE_DELAY_RANGE_SECONDS = (3.0, 5.0)
ENDPOINT_PROBE_MAX_PAGES_PER_CONTRACT = 3
PARTITION_PROBE_MAX_PAGES_PER_CONDITION = 10
PARTITION_PROBE_MAX_PARTITIONS = 31
PARTITION_CONTRIBUTION_THRESHOLD = 0.005
PHASE_C_SESSION_MODE = "saved-session"

PartitionKind = Literal["top_level_category", "leaf_category"]
PhaseCProbeExperiment = Literal[
    "endpoint-contract-probe-v1",
    "partition-probe-v1",
]


def canonical_phase_c_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(
            f"{field_name} must be an exact integer greater than or equal to {minimum}"
        )
    return value


def _nonblank(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or item != item.strip()
        for item in value
    ):
        raise ValueError(f"{field_name} must be a list of nonblank strings")
    return tuple(value)


def _ordered_distinct(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True, slots=True)
class OfferTodayPartitionDefinition:
    schema_version: int
    kind: PartitionKind
    category_code: int
    name: str
    parent_code: int
    level: int

    def __post_init__(self) -> None:
        if self.schema_version != PARTITION_SCHEMA_VERSION:
            raise ValueError("partition schema_version must equal 1")
        if self.kind not in {"top_level_category", "leaf_category"}:
            raise ValueError("unsupported partition kind")
        _exact_int(self.category_code, "category_code", minimum=1)
        _nonblank(self.name, "name")
        _exact_int(self.parent_code, "parent_code")
        expected_level = 1 if self.kind == "top_level_category" else 2
        if type(self.level) is not int or self.level != expected_level:
            raise ValueError("partition level does not match kind")
        if self.kind == "top_level_category" and self.parent_code != 0:
            raise ValueError("top-level partition parent_code must equal zero")
        if (
            self.kind == "leaf_category"
            and self.category_code == self.parent_code
        ):
            raise ValueError("same-code aliases cannot become leaf partitions")

    @property
    def partition_id(self) -> str:
        return canonical_phase_c_hash(self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "category_code": self.category_code,
            "name": self.name,
            "parent_code": self.parent_code,
            "level": self.level,
            "query_filters": {"jobFunctionCodes": [self.category_code]},
        }

    def to_payload(self) -> dict[str, Any]:
        return {"partition_id": self.partition_id, **self.identity_payload()}

    @classmethod
    def from_payload(cls, payload: Any) -> OfferTodayPartitionDefinition:
        expected = {
            "partition_id",
            "schema_version",
            "kind",
            "category_code",
            "name",
            "parent_code",
            "level",
            "query_filters",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("partition payload fields do not match")
        value = cls(
            schema_version=payload["schema_version"],
            kind=payload["kind"],
            category_code=payload["category_code"],
            name=payload["name"],
            parent_code=payload["parent_code"],
            level=payload["level"],
        )
        if payload["query_filters"] != value.identity_payload()["query_filters"]:
            raise ValueError("partition query filters do not match identity")
        if payload["partition_id"] != value.partition_id:
            raise ValueError("partition_id does not match canonical identity")
        return value


def _partition_from_category(
    category: OfferTodayCategory,
    *,
    kind: PartitionKind,
) -> OfferTodayPartitionDefinition:
    return OfferTodayPartitionDefinition(
        schema_version=PARTITION_SCHEMA_VERSION,
        kind=kind,
        category_code=category.code,
        name=category.name,
        parent_code=category.parent_code,
        level=category.level,
    )


def build_offertoday_partition_catalog() -> tuple[OfferTodayPartitionDefinition, ...]:
    top_level = tuple(
        _partition_from_category(category, kind="top_level_category")
        for category in OFFERTODAY_CATEGORIES_L1
    )
    leaves = tuple(
        _partition_from_category(category, kind="leaf_category")
        for category in iter_offertoday_leaf_categories()
    )
    partitions = (*top_level, *leaves)
    if len(partitions) != 462 or len(
        {partition.partition_id for partition in partitions}
    ) != len(partitions):
        raise ValueError("OfferToday partition catalog v1 identity is invalid")
    query_codes = [partition.category_code for partition in partitions]
    if len(query_codes) != len(set(query_codes)):
        raise ValueError("OfferToday partition query codes must be unique")
    return partitions


OFFERTODAY_PARTITION_CATALOG = build_offertoday_partition_catalog()
_PARTITIONS_BY_ID = {
    partition.partition_id: partition for partition in OFFERTODAY_PARTITION_CATALOG
}
_PARTITION_ORDER = {
    partition.partition_id: index
    for index, partition in enumerate(OFFERTODAY_PARTITION_CATALOG)
}


def offertoday_partition_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "category_catalog_version": OFFERTODAY_CATEGORY_CATALOG_VERSION,
        "category_catalog_hash": offertoday_category_catalog_hash(),
        "partitions": [
            partition.to_payload() for partition in OFFERTODAY_PARTITION_CATALOG
        ],
    }


def offertoday_partition_catalog_hash() -> str:
    return canonical_phase_c_hash(offertoday_partition_catalog_payload())


def offertoday_partition(partition_id: str) -> OfferTodayPartitionDefinition:
    if not isinstance(partition_id, str) or not partition_id:
        raise ValueError(f"unknown OfferToday partition: {partition_id}")
    try:
        return _PARTITIONS_BY_ID[partition_id]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown OfferToday partition: {partition_id}") from exc


def top_level_partition(category_code: int) -> OfferTodayPartitionDefinition:
    for partition in OFFERTODAY_PARTITION_CATALOG[:31]:
        if partition.category_code == category_code:
            return partition
    raise ValueError(f"unknown OfferToday top-level category: {category_code}")


@dataclass(frozen=True, slots=True)
class PhaseCRequestBudget:
    listing_logical: int
    listing_attempt_max: int
    detail: int = 0
    product_writes: int = 0

    def __post_init__(self) -> None:
        _exact_int(self.listing_logical, "listing_logical", minimum=1)
        _exact_int(self.listing_attempt_max, "listing_attempt_max", minimum=1)
        if self.listing_attempt_max < self.listing_logical:
            raise ValueError("listing_attempt_max cannot be below listing_logical")
        if self.detail != 0 or self.product_writes != 0:
            raise ValueError("Phase C request budgets require zero detail and writes")

    def to_payload(self) -> dict[str, int]:
        return {
            "listing_logical": self.listing_logical,
            "listing_attempt_max": self.listing_attempt_max,
            "detail": self.detail,
            "product_writes": self.product_writes,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCRequestBudget:
        expected = {"listing_logical", "listing_attempt_max", "detail", "product_writes"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C request budget fields do not match")
        return cls(**{key: payload[key] for key in expected})


@dataclass(frozen=True, slots=True)
class EndpointProbePlan:
    contract_ids: tuple[str, ...]
    category_code: int = 118000
    max_pages_per_contract: int = ENDPOINT_PROBE_MAX_PAGES_PER_CONTRACT
    max_attempts_per_page: int = PHASE_C_MAX_ATTEMPTS_PER_PAGE
    requested_page_size: int = PHASE_C_REQUESTED_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.contract_ids != tuple(
            contract.contract_id for contract in OFFERTODAY_ENDPOINT_CONTRACTS
        ):
            raise ValueError("endpoint probe contract order must match frozen v1")
        _exact_int(self.category_code, "category_code", minimum=1)
        if self.category_code != 118000:
            raise ValueError("endpoint probe category_code must equal 118000")
        if self.max_pages_per_contract != ENDPOINT_PROBE_MAX_PAGES_PER_CONTRACT:
            raise ValueError("endpoint probe max pages must match frozen v1")
        if self.max_attempts_per_page != PHASE_C_MAX_ATTEMPTS_PER_PAGE:
            raise ValueError("endpoint probe attempts must match frozen v1")
        if self.requested_page_size != PHASE_C_REQUESTED_PAGE_SIZE:
            raise ValueError("endpoint probe page size must match frozen v1")
        for contract_id in self.contract_ids:
            contract = offertoday_endpoint_contract(contract_id)
            if contract.allowed_rcd_types != (None,):
                raise ValueError("endpoint probe v1 requires omitted rcdType")

    @property
    def budget(self) -> PhaseCRequestBudget:
        logical = len(self.contract_ids) * self.max_pages_per_contract
        return PhaseCRequestBudget(
            listing_logical=logical,
            listing_attempt_max=logical * self.max_attempts_per_page,
        )

    @property
    def plan_hash(self) -> str:
        return canonical_phase_c_hash(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PARTITION_SCHEMA_VERSION,
            "contract_ids": list(self.contract_ids),
            "contracts": [
                offertoday_endpoint_contract(contract_id).to_payload()
                for contract_id in self.contract_ids
            ],
            "category_code": self.category_code,
            "rcd_type": None,
            "max_pages_per_contract": self.max_pages_per_contract,
            "max_attempts_per_page": self.max_attempts_per_page,
            "requested_page_size": self.requested_page_size,
            "require_empty_confirmation": True,
            "retry_delays_seconds": list(PHASE_C_RETRY_DELAYS_SECONDS),
            "page_delay_range_seconds": list(PHASE_C_PAGE_DELAY_RANGE_SECONDS),
            "session_mode": PHASE_C_SESSION_MODE,
            "budget": self.budget.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> EndpointProbePlan:
        expected = {
            "schema_version",
            "contract_ids",
            "contracts",
            "category_code",
            "rcd_type",
            "max_pages_per_contract",
            "max_attempts_per_page",
            "requested_page_size",
            "require_empty_confirmation",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "session_mode",
            "budget",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("endpoint probe plan fields do not match")
        if payload["schema_version"] != PARTITION_SCHEMA_VERSION:
            raise ValueError("endpoint probe plan schema version does not match")
        contract_ids = _string_tuple(payload["contract_ids"], "contract_ids")
        value = cls(
            contract_ids=contract_ids,
            category_code=payload["category_code"],
            max_pages_per_contract=payload["max_pages_per_contract"],
            max_attempts_per_page=payload["max_attempts_per_page"],
            requested_page_size=payload["requested_page_size"],
        )
        if (
            payload["rcd_type"] is not None
            or payload["require_empty_confirmation"] is not True
            or payload["retry_delays_seconds"] != list(PHASE_C_RETRY_DELAYS_SECONDS)
            or payload["page_delay_range_seconds"]
            != list(PHASE_C_PAGE_DELAY_RANGE_SECONDS)
            or payload["session_mode"] != PHASE_C_SESSION_MODE
        ):
            raise ValueError("endpoint probe controls do not match v1")
        if payload["contracts"] != [
            offertoday_endpoint_contract(contract_id).to_payload()
            for contract_id in contract_ids
        ]:
            raise ValueError("endpoint probe contracts do not match registry")
        if PhaseCRequestBudget.from_payload(payload["budget"]) != value.budget:
            raise ValueError("endpoint probe budget does not match plan")
        return value


def build_endpoint_probe_plan() -> EndpointProbePlan:
    return EndpointProbePlan(
        contract_ids=tuple(
            contract.contract_id for contract in OFFERTODAY_ENDPOINT_CONTRACTS
        )
    )


@dataclass(frozen=True, slots=True)
class PartitionProbePlan:
    endpoint_contract_id: str
    partition_ids: tuple[str, ...]
    max_pages_per_condition: int
    max_attempts_per_page: int = PHASE_C_MAX_ATTEMPTS_PER_PAGE
    requested_page_size: int = PHASE_C_REQUESTED_PAGE_SIZE

    def __post_init__(self) -> None:
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if contract.allowed_rcd_types != (None,):
            raise ValueError("partition probe v1 requires omitted rcdType")
        if not isinstance(self.partition_ids, tuple):
            raise ValueError("partition probe partition IDs must be a tuple")
        if not self.partition_ids or len(self.partition_ids) > PARTITION_PROBE_MAX_PARTITIONS:
            raise ValueError("partition probe requires between 1 and 31 partitions")
        if any(
            not isinstance(partition_id, str)
            or not partition_id
            or partition_id != partition_id.strip()
            for partition_id in self.partition_ids
        ):
            raise ValueError("partition probe partition IDs must be nonblank strings")
        if len(set(self.partition_ids)) != len(self.partition_ids):
            raise ValueError("partition probe partition IDs must be distinct")
        for partition_id in self.partition_ids:
            offertoday_partition(partition_id)
        expected_order = tuple(sorted(self.partition_ids, key=_PARTITION_ORDER.__getitem__))
        if self.partition_ids != expected_order:
            raise ValueError("partition probe partitions must use catalog order")
        if (
            type(self.max_pages_per_condition) is not int
            or not 1
            <= self.max_pages_per_condition
            <= PARTITION_PROBE_MAX_PAGES_PER_CONDITION
        ):
            raise ValueError("max_pages_per_condition must be in the range 1..10")
        if self.max_attempts_per_page != PHASE_C_MAX_ATTEMPTS_PER_PAGE:
            raise ValueError("partition probe attempts must match frozen v1")
        if self.requested_page_size != PHASE_C_REQUESTED_PAGE_SIZE:
            raise ValueError("partition probe page size must match frozen v1")

    @property
    def endpoint_contract(self) -> OfferTodayListingEndpointContract:
        return offertoday_endpoint_contract(self.endpoint_contract_id)

    @property
    def budget(self) -> PhaseCRequestBudget:
        logical = len(self.partition_ids) * self.max_pages_per_condition
        return PhaseCRequestBudget(
            listing_logical=logical,
            listing_attempt_max=logical * self.max_attempts_per_page,
        )

    @property
    def plan_hash(self) -> str:
        return canonical_phase_c_hash(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PARTITION_SCHEMA_VERSION,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract": self.endpoint_contract.to_payload(),
            "partition_catalog_hash": offertoday_partition_catalog_hash(),
            "partition_ids": list(self.partition_ids),
            "partitions": [
                offertoday_partition(partition_id).to_payload()
                for partition_id in self.partition_ids
            ],
            "rcd_type": None,
            "max_pages_per_condition": self.max_pages_per_condition,
            "max_attempts_per_page": self.max_attempts_per_page,
            "requested_page_size": self.requested_page_size,
            "require_empty_confirmation": True,
            "retry_delays_seconds": list(PHASE_C_RETRY_DELAYS_SECONDS),
            "page_delay_range_seconds": list(PHASE_C_PAGE_DELAY_RANGE_SECONDS),
            "session_mode": PHASE_C_SESSION_MODE,
            "budget": self.budget.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PartitionProbePlan:
        expected = {
            "schema_version",
            "endpoint_contract_id",
            "endpoint_contract",
            "partition_catalog_hash",
            "partition_ids",
            "partitions",
            "rcd_type",
            "max_pages_per_condition",
            "max_attempts_per_page",
            "requested_page_size",
            "require_empty_confirmation",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "session_mode",
            "budget",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("partition probe plan fields do not match")
        if payload["schema_version"] != PARTITION_SCHEMA_VERSION:
            raise ValueError("partition probe plan schema version does not match")
        value = cls(
            endpoint_contract_id=payload["endpoint_contract_id"],
            partition_ids=_string_tuple(payload["partition_ids"], "partition_ids"),
            max_pages_per_condition=payload["max_pages_per_condition"],
            max_attempts_per_page=payload["max_attempts_per_page"],
            requested_page_size=payload["requested_page_size"],
        )
        if payload["endpoint_contract"] != value.endpoint_contract.to_payload():
            raise ValueError("partition endpoint contract does not match registry")
        if payload["partition_catalog_hash"] != offertoday_partition_catalog_hash():
            raise ValueError("partition catalog hash does not match")
        if payload["partitions"] != [
            offertoday_partition(partition_id).to_payload()
            for partition_id in value.partition_ids
        ]:
            raise ValueError("partition definitions do not match catalog")
        if (
            payload["rcd_type"] is not None
            or payload["require_empty_confirmation"] is not True
            or payload["retry_delays_seconds"] != list(PHASE_C_RETRY_DELAYS_SECONDS)
            or payload["page_delay_range_seconds"]
            != list(PHASE_C_PAGE_DELAY_RANGE_SECONDS)
            or payload["session_mode"] != PHASE_C_SESSION_MODE
        ):
            raise ValueError("partition probe controls do not match v1")
        if PhaseCRequestBudget.from_payload(payload["budget"]) != value.budget:
            raise ValueError("partition probe budget does not match plan")
        return value


def build_partition_probe_plan(
    *,
    endpoint_contract_id: str,
    partition_ids: Sequence[str],
    max_pages_per_condition: int,
) -> PartitionProbePlan:
    explicit = tuple(partition_ids)
    if any(
        not isinstance(partition_id, str)
        or not partition_id
        or partition_id != partition_id.strip()
        for partition_id in explicit
    ):
        raise ValueError("partition IDs must be explicit nonblank strings")
    if len(set(explicit)) != len(explicit):
        raise ValueError("partition IDs must be explicit and distinct")
    for partition_id in explicit:
        offertoday_partition(partition_id)
    ordered = tuple(sorted(explicit, key=_PARTITION_ORDER.__getitem__))
    return PartitionProbePlan(
        endpoint_contract_id=endpoint_contract_id,
        partition_ids=ordered,
        max_pages_per_condition=max_pages_per_condition,
    )


def request_policy_for_contract(
    contract_id: str,
) -> OfferTodayListingRequestPolicy:
    contract = offertoday_endpoint_contract(contract_id)
    return OfferTodayListingRequestPolicy(
        protocol_version=2,
        pagination_mode=(
            "response-cursor" if contract.cursor_verified else "stateless-control"
        ),
        requested_page_size=PHASE_C_REQUESTED_PAGE_SIZE,
        browser_lifecycle="condition-local-runtime",
        variant_id=f"phase-c:{contract.contract_id}",
        repeat_index=1,
        endpoint_contract_id=contract.contract_id,
    )


def phase_c_request_policy_payload(contract_id: str) -> dict[str, Any]:
    policy = request_policy_for_contract(contract_id)
    return {
        "protocol_version": policy.protocol_version,
        "pagination_mode": policy.pagination_mode,
        "requested_page_size": policy.requested_page_size,
        "browser_lifecycle": policy.browser_lifecycle,
        "variant_id": policy.variant_id,
        "repeat_index": policy.repeat_index,
        "condition_restart_index": policy.condition_restart_index,
        "endpoint_contract_id": policy.endpoint_contract_id,
    }


def phase_c_request_policy_hash(contract_id: str) -> str:
    return canonical_phase_c_hash(phase_c_request_policy_payload(contract_id))


def partition_probe_policy_hash(plan: PartitionProbePlan) -> str:
    """Hash execution controls while excluding the selected partition cohort."""
    return canonical_phase_c_hash(
        {
            "schema_version": PARTITION_SCHEMA_VERSION,
            "endpoint_contract_id": plan.endpoint_contract_id,
            "endpoint_contract_hash": plan.endpoint_contract.contract_hash,
            "request_policy": phase_c_request_policy_payload(
                plan.endpoint_contract_id
            ),
            "rcd_type": None,
            "max_pages_per_condition": plan.max_pages_per_condition,
            "max_attempts_per_page": plan.max_attempts_per_page,
            "requested_page_size": plan.requested_page_size,
            "require_empty_confirmation": True,
            "retry_delays_seconds": list(PHASE_C_RETRY_DELAYS_SECONDS),
            "page_delay_range_seconds": list(PHASE_C_PAGE_DELAY_RANGE_SECONDS),
            "session_mode": PHASE_C_SESSION_MODE,
        }
    )


@dataclass(frozen=True, slots=True)
class PhaseCPageEvidence:
    page: int
    attempt: int
    classification: str
    stop_reason: str | None
    logical_request_id: str
    physical_attempt_id: str
    result_job_ids: tuple[str, ...]
    supplemental_job_ids: tuple[str, ...]
    terminal_signal: bool
    awaiting_empty_confirmation: bool
    contract_error: str | None
    reported_total: int | None

    def __post_init__(self) -> None:
        _exact_int(self.page, "page", minimum=1)
        _exact_int(self.attempt, "attempt", minimum=1)
        _nonblank(self.classification, "classification")
        if self.stop_reason is not None:
            _nonblank(self.stop_reason, "stop_reason")
        _sha256(self.logical_request_id, "logical_request_id")
        _sha256(self.physical_attempt_id, "physical_attempt_id")
        if len(set(self.result_job_ids)) != len(self.result_job_ids):
            raise ValueError("result_job_ids must be distinct within normalized page")
        if len(set(self.supplemental_job_ids)) != len(self.supplemental_job_ids):
            raise ValueError(
                "supplemental_job_ids must be distinct within normalized page"
            )
        for value in (*self.result_job_ids, *self.supplemental_job_ids):
            _nonblank(value, "job_id")
        if type(self.terminal_signal) is not bool:
            raise ValueError("terminal_signal must be an exact boolean")
        if type(self.awaiting_empty_confirmation) is not bool:
            raise ValueError("awaiting_empty_confirmation must be an exact boolean")
        if self.contract_error is not None:
            _nonblank(self.contract_error, "contract_error")
        if self.reported_total is not None:
            _exact_int(self.reported_total, "reported_total")

    @property
    def job_ids(self) -> tuple[str, ...]:
        return _ordered_distinct((*self.result_job_ids, *self.supplemental_job_ids))

    @property
    def successful(self) -> bool:
        return self.classification == "success"

    def to_payload(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "attempt": self.attempt,
            "classification": self.classification,
            "stop_reason": self.stop_reason,
            "logical_request_id": self.logical_request_id,
            "physical_attempt_id": self.physical_attempt_id,
            "result_job_ids": list(self.result_job_ids),
            "supplemental_job_ids": list(self.supplemental_job_ids),
            "terminal_signal": self.terminal_signal,
            "awaiting_empty_confirmation": self.awaiting_empty_confirmation,
            "contract_error": self.contract_error,
            "reported_total": self.reported_total,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCPageEvidence:
        expected = {
            "page",
            "attempt",
            "classification",
            "stop_reason",
            "logical_request_id",
            "physical_attempt_id",
            "result_job_ids",
            "supplemental_job_ids",
            "terminal_signal",
            "awaiting_empty_confirmation",
            "contract_error",
            "reported_total",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C page evidence fields do not match")
        values = dict(payload)
        values["result_job_ids"] = _string_tuple(
            values["result_job_ids"], "result_job_ids"
        )
        values["supplemental_job_ids"] = _string_tuple(
            values["supplemental_job_ids"], "supplemental_job_ids"
        )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class PhaseCConditionEvidence:
    partition_id: str
    endpoint_contract_id: str
    endpoint_contract_hash: str
    condition_id: str
    stop_reason: str
    is_complete: bool
    contract_verified: bool
    terminal_confirmed: bool
    empty_confirmation: bool
    gap_count: int
    identity_conflict_count: int
    identity_issue_count: int
    conservation_difference: int
    pages: tuple[PhaseCPageEvidence, ...]

    def __post_init__(self) -> None:
        offertoday_partition(self.partition_id)
        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("condition endpoint contract hash does not match")
        _sha256(self.condition_id, "condition_id")
        _nonblank(self.stop_reason, "stop_reason")
        for field_name in (
            "is_complete",
            "contract_verified",
            "terminal_confirmed",
            "empty_confirmation",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be an exact boolean")
        for field_name in (
            "gap_count",
            "identity_conflict_count",
            "identity_issue_count",
            "conservation_difference",
        ):
            _exact_int(getattr(self, field_name), field_name)
        if not isinstance(self.pages, tuple):
            raise ValueError("condition pages must be a tuple")
        if self.contract_verified and not (
            contract.cursor_verified and contract.terminal_verified
        ):
            raise ValueError("unverified endpoint cannot be marked contract_verified")
        if self.terminal_confirmed and (
            not self.is_complete or self.stop_reason != "natural_exhaustion"
        ):
            raise ValueError("terminal confirmation requires natural exhaustion")

    @property
    def job_ids(self) -> tuple[str, ...]:
        return _ordered_distinct(
            job_id for page in self.pages for job_id in page.job_ids
        )

    @property
    def logical_requests(self) -> int:
        return len({page.logical_request_id for page in self.pages})

    @property
    def physical_attempts(self) -> int:
        return len(self.pages)

    def to_payload(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract_hash": self.endpoint_contract_hash,
            "condition_id": self.condition_id,
            "stop_reason": self.stop_reason,
            "is_complete": self.is_complete,
            "contract_verified": self.contract_verified,
            "terminal_confirmed": self.terminal_confirmed,
            "empty_confirmation": self.empty_confirmation,
            "gap_count": self.gap_count,
            "identity_conflict_count": self.identity_conflict_count,
            "identity_issue_count": self.identity_issue_count,
            "conservation_difference": self.conservation_difference,
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "job_ids": list(self.job_ids),
            "pages": [page.to_payload() for page in self.pages],
        }

    @classmethod
    def from_payload(cls, payload: Any) -> PhaseCConditionEvidence:
        expected = {
            "partition_id",
            "endpoint_contract_id",
            "endpoint_contract_hash",
            "condition_id",
            "stop_reason",
            "is_complete",
            "contract_verified",
            "terminal_confirmed",
            "empty_confirmation",
            "gap_count",
            "identity_conflict_count",
            "identity_issue_count",
            "conservation_difference",
            "logical_requests",
            "physical_attempts",
            "job_ids",
            "pages",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("Phase C condition evidence fields do not match")
        raw_pages = payload["pages"]
        if not isinstance(raw_pages, list):
            raise ValueError("Phase C condition pages must be a list")
        value = cls(
            partition_id=payload["partition_id"],
            endpoint_contract_id=payload["endpoint_contract_id"],
            endpoint_contract_hash=payload["endpoint_contract_hash"],
            condition_id=payload["condition_id"],
            stop_reason=payload["stop_reason"],
            is_complete=payload["is_complete"],
            contract_verified=payload["contract_verified"],
            terminal_confirmed=payload["terminal_confirmed"],
            empty_confirmation=payload["empty_confirmation"],
            gap_count=payload["gap_count"],
            identity_conflict_count=payload["identity_conflict_count"],
            identity_issue_count=payload["identity_issue_count"],
            conservation_difference=payload["conservation_difference"],
            pages=tuple(PhaseCPageEvidence.from_payload(item) for item in raw_pages),
        )
        if payload["logical_requests"] != value.logical_requests:
            raise ValueError("condition logical request count does not match")
        if payload["physical_attempts"] != value.physical_attempts:
            raise ValueError("condition physical attempt count does not match")
        if _string_tuple(payload["job_ids"], "job_ids") != value.job_ids:
            raise ValueError("condition job IDs do not match page evidence")
        return value


def _identity_conservation_difference(
    pages: Sequence[ListingPageObservation],
) -> int:
    observed: set[str] = set()
    identified: set[str] = set()
    for observation in pages:
        evidence = observation.cursor_evidence
        if evidence is None:
            continue
        observed.update(evidence.result_job_ids)
        observed.update(evidence.supplemental_job_ids)
        identified.update(item.job_id for item in evidence.result_identity_pairs)
        identified.update(
            item.job_id for item in evidence.supplemental_identity_pairs
        )
    return len(observed.symmetric_difference(identified))


def condition_evidence_from_listing_result(
    *,
    partition_id: str,
    endpoint_contract_id: str,
    result: ListingRunResult,
) -> PhaseCConditionEvidence:
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    if len(result.condition_outcomes) != 1:
        raise ValueError("Phase C condition execution must contain one outcome")
    outcome = result.condition_outcomes[0]
    pages: list[PhaseCPageEvidence] = []
    observations = list(result.observations)
    for observation in observations:
        evidence = observation.cursor_evidence
        if not isinstance(evidence, OfferTodayListingPageEvidenceV2):
            raise ValueError("Phase C condition requires v2 page evidence")
        pages.append(
            PhaseCPageEvidence(
                page=observation.page,
                attempt=observation.attempt,
                classification=observation.classification,
                stop_reason=observation.stop_reason,
                logical_request_id=evidence.logical_request_id,
                physical_attempt_id=evidence.physical_attempt_id,
                result_job_ids=_ordered_distinct(evidence.result_job_ids),
                supplemental_job_ids=_ordered_distinct(
                    evidence.supplemental_job_ids
                ),
                terminal_signal=evidence.terminal_signal,
                awaiting_empty_confirmation=evidence.awaiting_empty_confirmation,
                contract_error=evidence.contract_error,
                reported_total=observation.reported_total,
            )
        )
    contract_errors = [page.contract_error for page in pages if page.contract_error]
    contract_verified = (
        contract.cursor_verified
        and contract.terminal_verified
        and not contract_errors
    )
    empty_confirmation = any(
        page.terminal_signal and not page.job_ids for page in pages
    )
    return PhaseCConditionEvidence(
        partition_id=partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        condition_id=outcome.condition.condition_id,
        stop_reason=outcome.stop_reason,
        is_complete=outcome.is_complete,
        contract_verified=contract_verified,
        terminal_confirmed=(
            contract_verified
            and outcome.is_complete
            and outcome.stop_reason == "natural_exhaustion"
        ),
        empty_confirmation=empty_confirmation,
        gap_count=len(result.gaps),
        identity_conflict_count=len(result.identity_conflicts),
        identity_issue_count=len(result.identity_issues),
        conservation_difference=_identity_conservation_difference(observations),
        pages=tuple(pages),
    )


@dataclass(frozen=True, slots=True)
class PhaseCProbeExecution:
    experiment: PhaseCProbeExperiment
    plan: EndpointProbePlan | PartitionProbePlan
    conditions: tuple[PhaseCConditionEvidence, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.experiment not in {
            ENDPOINT_PROBE_EXPERIMENT,
            PARTITION_PROBE_EXPERIMENT,
        }:
            raise ValueError("unsupported Phase C probe experiment")
        if self.failure_reason is not None:
            _nonblank(self.failure_reason, "failure_reason")
        expected: tuple[tuple[str, str], ...]
        if self.experiment == ENDPOINT_PROBE_EXPERIMENT:
            if not isinstance(self.plan, EndpointProbePlan):
                raise ValueError("endpoint probe requires EndpointProbePlan")
            partition_id = top_level_partition(self.plan.category_code).partition_id
            expected = tuple(
                (partition_id, contract_id) for contract_id in self.plan.contract_ids
            )
        else:
            if not isinstance(self.plan, PartitionProbePlan):
                raise ValueError("partition probe requires PartitionProbePlan")
            expected = tuple(
                (partition_id, self.plan.endpoint_contract_id)
                for partition_id in self.plan.partition_ids
            )
        actual = tuple(
            (condition.partition_id, condition.endpoint_contract_id)
            for condition in self.conditions
        )
        if actual != expected[: len(actual)]:
            raise ValueError("Phase C condition execution order does not match plan")
        if self.failure_reason is None and len(actual) != len(expected):
            raise ValueError("completed Phase C probe requires every condition")
        if self.logical_requests > self.plan.budget.listing_logical:
            raise ValueError("Phase C logical request budget exceeded")
        if self.physical_attempts > self.plan.budget.listing_attempt_max:
            raise ValueError("Phase C physical request budget exceeded")

    @property
    def logical_requests(self) -> int:
        return sum(condition.logical_requests for condition in self.conditions)

    @property
    def physical_attempts(self) -> int:
        return sum(condition.physical_attempts for condition in self.conditions)

    @property
    def accepted(self) -> bool:
        return (
            self.failure_reason is None
            and bool(self.conditions)
            and all(
                condition.contract_verified
                and condition.terminal_confirmed
                and condition.empty_confirmation
                and condition.gap_count == 0
                and condition.identity_conflict_count == 0
                and condition.identity_issue_count == 0
                and condition.conservation_difference == 0
                for condition in self.conditions
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PARTITION_SCHEMA_VERSION,
            "experiment": self.experiment,
            "plan": self.plan.to_payload(),
            "plan_hash": self.plan.plan_hash,
            "conditions": [condition.to_payload() for condition in self.conditions],
            "failure_reason": self.failure_reason,
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "accepted": self.accepted,
            "candidate_frozen": False,
        }


def phase_c_probe_execution_from_payload(payload: Any) -> PhaseCProbeExecution:
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
        "candidate_frozen",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("Phase C probe payload fields do not match")
    if payload["schema_version"] != PARTITION_SCHEMA_VERSION:
        raise ValueError("Phase C probe schema version does not match")
    experiment = payload["experiment"]
    if experiment == ENDPOINT_PROBE_EXPERIMENT:
        plan: EndpointProbePlan | PartitionProbePlan = EndpointProbePlan.from_payload(
            payload["plan"]
        )
    elif experiment == PARTITION_PROBE_EXPERIMENT:
        plan = PartitionProbePlan.from_payload(payload["plan"])
    else:
        raise ValueError("unsupported Phase C probe experiment")
    raw_conditions = payload["conditions"]
    if not isinstance(raw_conditions, list):
        raise ValueError("Phase C probe conditions must be a list")
    value = PhaseCProbeExecution(
        experiment=experiment,
        plan=plan,
        conditions=tuple(
            PhaseCConditionEvidence.from_payload(item) for item in raw_conditions
        ),
        failure_reason=payload["failure_reason"],
    )
    if payload["plan_hash"] != value.plan.plan_hash:
        raise ValueError("Phase C probe plan hash does not match")
    if payload["logical_requests"] != value.logical_requests:
        raise ValueError("Phase C probe logical request count does not match")
    if payload["physical_attempts"] != value.physical_attempts:
        raise ValueError("Phase C probe physical attempt count does not match")
    if payload["accepted"] is not value.accepted:
        raise ValueError("Phase C probe acceptance does not match")
    if payload["candidate_frozen"] is not False:
        raise ValueError("Phase C probe cannot freeze a candidate")
    return value


@dataclass(frozen=True, slots=True)
class HighValuePartitionOverride:
    partition_id: str
    rationale: str

    def __post_init__(self) -> None:
        offertoday_partition(self.partition_id)
        _nonblank(self.rationale, "rationale")

    def to_payload(self) -> dict[str, str]:
        return {"partition_id": self.partition_id, "rationale": self.rationale}


HIGH_VALUE_PARTITION_OVERRIDES_V1: tuple[HighValuePartitionOverride, ...] = ()


@dataclass(frozen=True, slots=True)
class PartitionContribution:
    partition_id: str
    retained: bool
    rejection_reasons: tuple[str, ...]
    distinct_id_count: int
    unique_contribution_ids: tuple[str, ...]
    contribution_ratio: float
    overlap_ids: tuple[str, ...]
    logical_requests: int
    physical_attempts: int
    logical_request_cost_per_unique_id: float | None
    physical_attempt_cost_per_unique_id: float | None
    successful_request_new_ids: tuple[int, ...]
    last_100_new_ids: int | None
    last_100_ratio: float | None
    high_value_rationale: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "retained": self.retained,
            "rejection_reasons": list(self.rejection_reasons),
            "distinct_id_count": self.distinct_id_count,
            "unique_contribution_ids": list(self.unique_contribution_ids),
            "contribution_ratio": self.contribution_ratio,
            "overlap_ids": list(self.overlap_ids),
            "logical_requests": self.logical_requests,
            "physical_attempts": self.physical_attempts,
            "logical_request_cost_per_unique_id": (
                self.logical_request_cost_per_unique_id
            ),
            "physical_attempt_cost_per_unique_id": (
                self.physical_attempt_cost_per_unique_id
            ),
            "successful_request_new_ids": list(self.successful_request_new_ids),
            "last_100_new_ids": self.last_100_new_ids,
            "last_100_ratio": self.last_100_ratio,
            "high_value_rationale": self.high_value_rationale,
        }


@dataclass(frozen=True, slots=True)
class PartitionComparison:
    accepted: bool
    reference_union_ids: tuple[str, ...]
    contributions: tuple[PartitionContribution, ...]

    @property
    def reference_union_hash(self) -> str:
        return canonical_phase_c_hash(list(self.reference_union_ids))

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reference_union_ids": list(self.reference_union_ids),
            "reference_union_hash": self.reference_union_hash,
            "contribution_threshold": PARTITION_CONTRIBUTION_THRESHOLD,
            "high_value_overrides": [
                item.to_payload() for item in HIGH_VALUE_PARTITION_OVERRIDES_V1
            ],
            "contributions": [item.to_payload() for item in self.contributions],
            "candidate_frozen": False,
        }


def _successful_request_curve(
    condition: PhaseCConditionEvidence,
) -> tuple[int, ...]:
    seen: set[str] = set()
    counts: list[int] = []
    for page in condition.pages:
        if not page.successful:
            continue
        page_ids = set(page.job_ids)
        counts.append(len(page_ids - seen))
        seen.update(page_ids)
    return tuple(counts)


def compare_partition_conditions(
    conditions: Sequence[PhaseCConditionEvidence],
    *,
    high_value_overrides: Sequence[HighValuePartitionOverride] = (
        HIGH_VALUE_PARTITION_OVERRIDES_V1
    ),
) -> PartitionComparison:
    if not conditions:
        raise ValueError("partition comparison requires condition evidence")
    if len({condition.partition_id for condition in conditions}) != len(conditions):
        raise ValueError("partition comparison condition IDs must be distinct")
    ordered = tuple(sorted(conditions, key=lambda item: _PARTITION_ORDER[item.partition_id]))
    if tuple(conditions) != ordered:
        raise ValueError("partition comparison conditions must use catalog order")
    overrides = {item.partition_id: item.rationale for item in high_value_overrides}
    if len(overrides) != len(high_value_overrides):
        raise ValueError("high-value overrides must be distinct")

    reference_union = _ordered_distinct(
        job_id for condition in conditions for job_id in condition.job_ids
    )
    reference_set = set(reference_union)
    prior_ids: set[str] = set()
    contributions: list[PartitionContribution] = []
    for condition in conditions:
        condition_ids = set(condition.job_ids)
        unique_ids = tuple(sorted(condition_ids - prior_ids))
        overlap_ids = tuple(sorted(condition_ids & prior_ids))
        ratio = len(unique_ids) / len(reference_set) if reference_set else 0.0
        rationale = overrides.get(condition.partition_id)
        numerically_useful = ratio >= PARTITION_CONTRIBUTION_THRESHOLD
        hard_reasons: list[str] = []
        if not condition.contract_verified:
            hard_reasons.append("unverified_endpoint_contract")
        if not condition.terminal_confirmed:
            hard_reasons.append("terminal_not_confirmed")
        if not condition.empty_confirmation:
            hard_reasons.append("missing_empty_confirmation")
        if condition.gap_count:
            hard_reasons.append("unresolved_gap")
        if condition.identity_conflict_count:
            hard_reasons.append("identity_conflict")
        if condition.identity_issue_count:
            hard_reasons.append("identity_issue")
        if condition.conservation_difference:
            hard_reasons.append("conservation_difference")
        if not numerically_useful and rationale is None:
            hard_reasons.append("insufficient_unique_contribution")
        retained = not hard_reasons
        curve = _successful_request_curve(condition)
        last_100 = sum(curve[-100:]) if len(curve) >= 100 else None
        last_100_ratio = (
            last_100 / len(reference_set)
            if last_100 is not None and reference_set
            else None
        )
        contributions.append(
            PartitionContribution(
                partition_id=condition.partition_id,
                retained=retained,
                rejection_reasons=tuple(hard_reasons),
                distinct_id_count=len(condition_ids),
                unique_contribution_ids=unique_ids,
                contribution_ratio=ratio,
                overlap_ids=overlap_ids,
                logical_requests=condition.logical_requests,
                physical_attempts=condition.physical_attempts,
                logical_request_cost_per_unique_id=(
                    condition.logical_requests / len(unique_ids)
                    if unique_ids
                    else None
                ),
                physical_attempt_cost_per_unique_id=(
                    condition.physical_attempts / len(unique_ids)
                    if unique_ids
                    else None
                ),
                successful_request_new_ids=curve,
                last_100_new_ids=last_100,
                last_100_ratio=last_100_ratio,
                high_value_rationale=rationale,
            )
        )
        if retained:
            prior_ids.update(condition_ids)
    return PartitionComparison(
        accepted=any(item.retained for item in contributions),
        reference_union_ids=tuple(sorted(reference_set)),
        contributions=tuple(contributions),
    )


def comparison_payload(
    conditions: Sequence[PhaseCConditionEvidence],
) -> dict[str, Any]:
    decision = compare_partition_conditions(conditions)
    return {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "experiment": PARTITION_COMPARISON_EXPERIMENT,
        "partition_catalog_hash": offertoday_partition_catalog_hash(),
        "inputs": [condition.to_payload() for condition in conditions],
        "input_set_hash": canonical_phase_c_hash(
            [condition.to_payload() for condition in conditions]
        ),
        "decision": decision.to_payload(),
    }


def validate_comparison_payload(payload: Any) -> PartitionComparison:
    expected = {
        "schema_version",
        "experiment",
        "partition_catalog_hash",
        "inputs",
        "input_set_hash",
        "decision",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("partition comparison payload fields do not match")
    if (
        payload["schema_version"] != PARTITION_SCHEMA_VERSION
        or payload["experiment"] != PARTITION_COMPARISON_EXPERIMENT
        or payload["partition_catalog_hash"] != offertoday_partition_catalog_hash()
    ):
        raise ValueError("partition comparison contract does not match v1")
    raw_inputs = payload["inputs"]
    if not isinstance(raw_inputs, list):
        raise ValueError("partition comparison inputs must be a list")
    conditions = tuple(
        PhaseCConditionEvidence.from_payload(item) for item in raw_inputs
    )
    if payload["input_set_hash"] != canonical_phase_c_hash(raw_inputs):
        raise ValueError("partition comparison input_set_hash does not match")
    decision = compare_partition_conditions(conditions)
    if payload["decision"] != decision.to_payload():
        raise ValueError("partition comparison decision does not replay")
    return decision
