from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
)
from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.listing_runner import ListingRunResult
from app.sources.offertoday.research.partition_research import (
    OFFERTODAY_PARTITION_CATALOG,
    OfferTodayPartitionDefinition,
    offertoday_partition,
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CENSUS_CATEGORY_IDS = tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
_FIXED_REPEAT_CATEGORY_IDS = (118000, 112000, 127000)
_PHASE_D_MAX_PAGES_PER_CONDITION = 500
_PHASE_D_MAX_ATTEMPTS_PER_PAGE = 3
_PHASE_D_RETRY_DELAYS_SECONDS = (5.0, 15.0)
_PHASE_D_PAGE_DELAY_RANGE_SECONDS = (3.0, 5.0)
_PHASE_D_SESSION_MODE = "saved-session"
_PHASE_D_TERMINAL_POLICY = "cursor-terminal-empty-confirmation-v1"
_PHASE_D_DEFERRED_ISSUE_IDS = (4, 5)


@dataclass(frozen=True, slots=True)
class DiscoveryCandidateV2:
    candidate_version: int
    endpoint: str
    rcd_type: int | None
    category_ids: tuple[int, ...]
    pagination_mode: str
    requested_page_size: int
    browser_lifecycle: str
    terminal_policy: str
    max_pages_per_condition: int
    require_empty_confirmation: bool
    max_attempts_per_page: int
    retry_delays_seconds: tuple[float, ...]
    page_delay_range_seconds: tuple[float, float]
    session_mode: str
    fixed_repeat_category_ids: tuple[int, ...]
    source_artifact_hash: str
    comparison_artifact_hash: str

    def __post_init__(self) -> None:
        if type(self.candidate_version) is not int or self.candidate_version != 2:
            raise ValueError("candidate_version must equal 2")
        if self.endpoint not in {"search", "browse"}:
            raise ValueError("endpoint must be 'search' or 'browse'")
        if self.rcd_type is not None and type(self.rcd_type) is not int:
            raise ValueError("rcd_type must be an int or None")
        if (
            not self.category_ids
            or any(type(value) is not int or value < 1 for value in self.category_ids)
            or len(set(self.category_ids)) != len(self.category_ids)
        ):
            raise ValueError("category_ids must be distinct positive exact integers")
        if self.pagination_mode != "response-cursor":
            raise ValueError("pagination_mode must equal 'response-cursor'")
        if type(self.requested_page_size) is not int or self.requested_page_size < 1:
            raise ValueError("requested_page_size must be a positive exact integer")
        if self.browser_lifecycle not in {
            "shared-variant-runtime",
            "condition-local-runtime",
            "restart-each-page",
        }:
            raise ValueError("unsupported browser_lifecycle")
        if self.terminal_policy != "cursor-terminal-empty-confirmation-v1":
            raise ValueError("unsupported terminal_policy")
        for field_name, value in (
            ("max_pages_per_condition", self.max_pages_per_condition),
            ("max_attempts_per_page", self.max_attempts_per_page),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{field_name} must be a positive exact integer")
        if type(self.require_empty_confirmation) is not bool:
            raise ValueError("require_empty_confirmation must be an exact boolean")
        if (
            not isinstance(self.retry_delays_seconds, tuple)
            or any(
                type(value) not in (int, float) or value < 0
                or not math.isfinite(value)
                for value in self.retry_delays_seconds
            )
        ):
            raise ValueError("retry_delays_seconds must be nonnegative numbers")
        if (
            not isinstance(self.page_delay_range_seconds, tuple)
            or len(self.page_delay_range_seconds) != 2
            or any(
                type(value) not in (int, float) or value < 0
                or not math.isfinite(value)
                for value in self.page_delay_range_seconds
            )
            or self.page_delay_range_seconds[0] > self.page_delay_range_seconds[1]
        ):
            raise ValueError("page_delay_range_seconds is invalid")
        if self.session_mode not in {
            "fresh-headless",
            "storage-state",
            "reusable-browser",
        }:
            raise ValueError("unsupported session_mode")
        if self.fixed_repeat_category_ids != _FIXED_REPEAT_CATEGORY_IDS:
            raise ValueError("fixed_repeat_category_ids must equal the frozen cohort")
        for field_name in ("source_artifact_hash", "comparison_artifact_hash"):
            if _SHA256_RE.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"{field_name} must be a lowercase SHA-256")

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "candidate_version": self.candidate_version,
            "endpoint": self.endpoint,
            "rcd_type": self.rcd_type,
            "category_ids": list(self.category_ids),
            "pagination_mode": self.pagination_mode,
            "requested_page_size": self.requested_page_size,
            "browser_lifecycle": self.browser_lifecycle,
            "terminal_policy": self.terminal_policy,
            "max_pages_per_condition": self.max_pages_per_condition,
            "require_empty_confirmation": self.require_empty_confirmation,
            "max_attempts_per_page": self.max_attempts_per_page,
            "retry_delays_seconds": list(self.retry_delays_seconds),
            "page_delay_range_seconds": list(self.page_delay_range_seconds),
            "session_mode": self.session_mode,
            "fixed_repeat_category_ids": list(self.fixed_repeat_category_ids),
            "source_artifact_hash": self.source_artifact_hash,
            "comparison_artifact_hash": self.comparison_artifact_hash,
        }

    @property
    def candidate_hash(self) -> str:
        canonical = json.dumps(
            self._canonical_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "candidate_hash": self.candidate_hash}

    @classmethod
    def from_payload(cls, payload: Any) -> "DiscoveryCandidateV2":
        expected_keys = {
            "candidate_version",
            "endpoint",
            "rcd_type",
            "category_ids",
            "pagination_mode",
            "requested_page_size",
            "browser_lifecycle",
            "terminal_policy",
            "max_pages_per_condition",
            "require_empty_confirmation",
            "max_attempts_per_page",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "session_mode",
            "fixed_repeat_category_ids",
            "source_artifact_hash",
            "comparison_artifact_hash",
            "candidate_hash",
        }
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError("v2 candidate payload fields do not match the contract")
        for field_name in (
            "category_ids",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "fixed_repeat_category_ids",
        ):
            if not isinstance(payload[field_name], list):
                raise ValueError(f"{field_name} must be a list")
        candidate = cls(
            candidate_version=payload["candidate_version"],
            endpoint=payload["endpoint"],
            rcd_type=payload["rcd_type"],
            category_ids=tuple(payload["category_ids"]),
            pagination_mode=payload["pagination_mode"],
            requested_page_size=payload["requested_page_size"],
            browser_lifecycle=payload["browser_lifecycle"],
            terminal_policy=payload["terminal_policy"],
            max_pages_per_condition=payload["max_pages_per_condition"],
            require_empty_confirmation=payload["require_empty_confirmation"],
            max_attempts_per_page=payload["max_attempts_per_page"],
            retry_delays_seconds=tuple(payload["retry_delays_seconds"]),
            page_delay_range_seconds=tuple(payload["page_delay_range_seconds"]),
            session_mode=payload["session_mode"],
            fixed_repeat_category_ids=tuple(payload["fixed_repeat_category_ids"]),
            source_artifact_hash=payload["source_artifact_hash"],
            comparison_artifact_hash=payload["comparison_artifact_hash"],
        )
        if payload["candidate_hash"] != candidate.candidate_hash:
            raise ValueError("candidate_hash does not match the v2 canonical payload")
        return candidate


@dataclass(frozen=True, slots=True)
class DiscoveryPolicyCandidateV2:
    """Frozen Phase C policy used only by the cursor-correct Phase D path.

    ``DiscoveryCandidateV2`` above is immutable Phase B evidence.  This
    separately named contract composes the accepted endpoint/partition policy
    without widening that historical payload schema.
    """

    candidate_version: int
    endpoint_contract_id: str
    endpoint_contract_hash: str
    endpoint: str
    rcd_type: int | None
    category_catalog_version: int
    category_catalog_hash: str
    partition_catalog_hash: str
    phase_d_partitions: tuple[OfferTodayPartitionDefinition, ...]
    retained_partition_ids: tuple[str, ...]
    retained_condition_hashes: tuple[str, ...]
    pagination_mode: str
    requested_page_size: int
    browser_lifecycle: str
    request_policy_hash: str
    terminal_policy: str
    max_pages_per_condition: int
    require_empty_confirmation: bool
    max_attempts_per_page: int
    retry_delays_seconds: tuple[float, ...]
    page_delay_range_seconds: tuple[float, float]
    session_mode: str
    fixed_repeat_category_ids: tuple[int, ...]
    phase_b_comparison_artifact_hash: str
    phase_c_comparison_artifact_hash: str
    source_artifact_hash: str
    deferred_issue_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.candidate_version) is not int or self.candidate_version != 2:
            raise ValueError("candidate_version must equal 2")

        contract = offertoday_endpoint_contract(self.endpoint_contract_id)
        if self.endpoint_contract_hash != contract.contract_hash:
            raise ValueError("endpoint_contract_hash does not match the registry")
        if self.endpoint != contract.endpoint:
            raise ValueError("endpoint does not match the endpoint contract")
        if not contract.cursor_verified or not contract.terminal_verified:
            raise ValueError("Phase D requires a verified cursor/terminal contract")
        if self.rcd_type not in contract.allowed_rcd_types:
            raise ValueError("rcd_type is not allowed by the endpoint contract")

        if self.category_catalog_version != OFFERTODAY_CATEGORY_CATALOG_VERSION:
            raise ValueError("category_catalog_version does not match the registry")
        if self.category_catalog_hash != offertoday_category_catalog_hash():
            raise ValueError("category_catalog_hash does not match the registry")
        if self.partition_catalog_hash != offertoday_partition_catalog_hash():
            raise ValueError("partition_catalog_hash does not match the registry")

        expected_partitions = tuple(
            top_level_partition(category.code)
            for category in OFFERTODAY_CATEGORIES_L1
        )
        if (
            not isinstance(self.phase_d_partitions, tuple)
            or self.phase_d_partitions != expected_partitions
        ):
            raise ValueError(
                "phase_d_partitions must equal all top-level partitions in catalog order"
            )

        catalog_order = {
            partition.partition_id: index
            for index, partition in enumerate(OFFERTODAY_PARTITION_CATALOG)
        }
        if (
            not isinstance(self.retained_partition_ids, tuple)
            or not self.retained_partition_ids
            or len(set(self.retained_partition_ids))
            != len(self.retained_partition_ids)
        ):
            raise ValueError("retained_partition_ids must be a nonempty distinct tuple")
        for partition_id in self.retained_partition_ids:
            offertoday_partition(partition_id)
        if self.retained_partition_ids != tuple(
            sorted(self.retained_partition_ids, key=catalog_order.__getitem__)
        ):
            raise ValueError("retained_partition_ids must use catalog order")
        if (
            not isinstance(self.retained_condition_hashes, tuple)
            or len(self.retained_condition_hashes)
            != len(self.retained_partition_ids)
            or any(
                _SHA256_RE.fullmatch(value) is None
                for value in self.retained_condition_hashes
            )
        ):
            raise ValueError(
                "retained_condition_hashes must bind every retained partition"
            )

        locked_values = {
            "pagination_mode": (self.pagination_mode, "response-cursor"),
            "requested_page_size": (self.requested_page_size, 10),
            "browser_lifecycle": (
                self.browser_lifecycle,
                "condition-local-runtime",
            ),
            "request_policy_hash": (
                self.request_policy_hash,
                phase_c_request_policy_hash(self.endpoint_contract_id),
            ),
            "terminal_policy": (self.terminal_policy, _PHASE_D_TERMINAL_POLICY),
            "max_pages_per_condition": (
                self.max_pages_per_condition,
                _PHASE_D_MAX_PAGES_PER_CONDITION,
            ),
            "require_empty_confirmation": (
                self.require_empty_confirmation,
                True,
            ),
            "max_attempts_per_page": (
                self.max_attempts_per_page,
                _PHASE_D_MAX_ATTEMPTS_PER_PAGE,
            ),
            "retry_delays_seconds": (
                self.retry_delays_seconds,
                _PHASE_D_RETRY_DELAYS_SECONDS,
            ),
            "page_delay_range_seconds": (
                self.page_delay_range_seconds,
                _PHASE_D_PAGE_DELAY_RANGE_SECONDS,
            ),
            "session_mode": (self.session_mode, _PHASE_D_SESSION_MODE),
            "fixed_repeat_category_ids": (
                self.fixed_repeat_category_ids,
                _FIXED_REPEAT_CATEGORY_IDS,
            ),
            "deferred_issue_ids": (
                self.deferred_issue_ids,
                _PHASE_D_DEFERRED_ISSUE_IDS,
            ),
        }
        for field_name, (actual, expected) in locked_values.items():
            if actual != expected:
                raise ValueError(f"{field_name} must equal the locked Phase D value")

        for field_name in (
            "phase_b_comparison_artifact_hash",
            "phase_c_comparison_artifact_hash",
            "source_artifact_hash",
        ):
            if _SHA256_RE.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"{field_name} must be a lowercase SHA-256")

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "candidate_version": self.candidate_version,
            "endpoint_contract_id": self.endpoint_contract_id,
            "endpoint_contract_hash": self.endpoint_contract_hash,
            "endpoint": self.endpoint,
            "rcd_type": self.rcd_type,
            "category_catalog_version": self.category_catalog_version,
            "category_catalog_hash": self.category_catalog_hash,
            "partition_catalog_hash": self.partition_catalog_hash,
            "phase_d_partitions": [
                partition.to_payload() for partition in self.phase_d_partitions
            ],
            "retained_partition_ids": list(self.retained_partition_ids),
            "retained_condition_hashes": list(self.retained_condition_hashes),
            "pagination_mode": self.pagination_mode,
            "requested_page_size": self.requested_page_size,
            "browser_lifecycle": self.browser_lifecycle,
            "request_policy_hash": self.request_policy_hash,
            "terminal_policy": self.terminal_policy,
            "max_pages_per_condition": self.max_pages_per_condition,
            "require_empty_confirmation": self.require_empty_confirmation,
            "max_attempts_per_page": self.max_attempts_per_page,
            "retry_delays_seconds": list(self.retry_delays_seconds),
            "page_delay_range_seconds": list(self.page_delay_range_seconds),
            "session_mode": self.session_mode,
            "fixed_repeat_category_ids": list(self.fixed_repeat_category_ids),
            "phase_b_comparison_artifact_hash": (
                self.phase_b_comparison_artifact_hash
            ),
            "phase_c_comparison_artifact_hash": (
                self.phase_c_comparison_artifact_hash
            ),
            "source_artifact_hash": self.source_artifact_hash,
            "deferred_issue_ids": list(self.deferred_issue_ids),
        }

    @property
    def candidate_hash(self) -> str:
        canonical = json.dumps(
            self._canonical_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {**self._canonical_payload(), "candidate_hash": self.candidate_hash}

    @classmethod
    def from_payload(cls, payload: Any) -> "DiscoveryPolicyCandidateV2":
        expected_keys = {
            "candidate_version",
            "endpoint_contract_id",
            "endpoint_contract_hash",
            "endpoint",
            "rcd_type",
            "category_catalog_version",
            "category_catalog_hash",
            "partition_catalog_hash",
            "phase_d_partitions",
            "retained_partition_ids",
            "retained_condition_hashes",
            "pagination_mode",
            "requested_page_size",
            "browser_lifecycle",
            "request_policy_hash",
            "terminal_policy",
            "max_pages_per_condition",
            "require_empty_confirmation",
            "max_attempts_per_page",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "session_mode",
            "fixed_repeat_category_ids",
            "phase_b_comparison_artifact_hash",
            "phase_c_comparison_artifact_hash",
            "source_artifact_hash",
            "deferred_issue_ids",
            "candidate_hash",
        }
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError(
                "Phase D discovery candidate payload fields do not match"
            )
        for field_name in (
            "phase_d_partitions",
            "retained_partition_ids",
            "retained_condition_hashes",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "fixed_repeat_category_ids",
            "deferred_issue_ids",
        ):
            if not isinstance(payload[field_name], list):
                raise ValueError(f"{field_name} must be a list")
        candidate = cls(
            candidate_version=payload["candidate_version"],
            endpoint_contract_id=payload["endpoint_contract_id"],
            endpoint_contract_hash=payload["endpoint_contract_hash"],
            endpoint=payload["endpoint"],
            rcd_type=payload["rcd_type"],
            category_catalog_version=payload["category_catalog_version"],
            category_catalog_hash=payload["category_catalog_hash"],
            partition_catalog_hash=payload["partition_catalog_hash"],
            phase_d_partitions=tuple(
                OfferTodayPartitionDefinition.from_payload(item)
                for item in payload["phase_d_partitions"]
            ),
            retained_partition_ids=tuple(payload["retained_partition_ids"]),
            retained_condition_hashes=tuple(
                payload["retained_condition_hashes"]
            ),
            pagination_mode=payload["pagination_mode"],
            requested_page_size=payload["requested_page_size"],
            browser_lifecycle=payload["browser_lifecycle"],
            request_policy_hash=payload["request_policy_hash"],
            terminal_policy=payload["terminal_policy"],
            max_pages_per_condition=payload["max_pages_per_condition"],
            require_empty_confirmation=payload["require_empty_confirmation"],
            max_attempts_per_page=payload["max_attempts_per_page"],
            retry_delays_seconds=tuple(payload["retry_delays_seconds"]),
            page_delay_range_seconds=tuple(
                payload["page_delay_range_seconds"]
            ),
            session_mode=payload["session_mode"],
            fixed_repeat_category_ids=tuple(
                payload["fixed_repeat_category_ids"]
            ),
            phase_b_comparison_artifact_hash=payload[
                "phase_b_comparison_artifact_hash"
            ],
            phase_c_comparison_artifact_hash=payload[
                "phase_c_comparison_artifact_hash"
            ],
            source_artifact_hash=payload["source_artifact_hash"],
            deferred_issue_ids=tuple(payload["deferred_issue_ids"]),
        )
        if payload["candidate_hash"] != candidate.candidate_hash:
            raise ValueError("candidate_hash does not match the Phase D payload")
        return candidate


@dataclass(frozen=True, slots=True)
class CensusCandidate:
    endpoint: str
    rcd_type: int | None
    category_ids: tuple[int, ...]
    page_size: int
    max_pages_per_condition: int
    require_empty_confirmation: bool
    max_attempts_per_page: int
    retry_delays_seconds: tuple[float, ...]
    page_delay_range_seconds: tuple[float, float]
    session_mode: str
    fixed_repeat_category_ids: tuple[int, ...]
    source_artifact_hash: str
    rejected_variants: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        locked_values = {
            "category_ids": (self.category_ids, _CENSUS_CATEGORY_IDS),
            "page_size": (self.page_size, 50),
            "max_pages_per_condition": (self.max_pages_per_condition, 500),
            "require_empty_confirmation": (self.require_empty_confirmation, True),
            "max_attempts_per_page": (self.max_attempts_per_page, 3),
            "retry_delays_seconds": (self.retry_delays_seconds, (5.0, 15.0)),
            "page_delay_range_seconds": (
                self.page_delay_range_seconds,
                (3.0, 5.0),
            ),
            "session_mode": (self.session_mode, "fresh-headless"),
            "fixed_repeat_category_ids": (
                self.fixed_repeat_category_ids,
                _FIXED_REPEAT_CATEGORY_IDS,
            ),
        }
        if self.endpoint not in {"search", "browse"}:
            raise ValueError("endpoint must be 'search' or 'browse'")
        if self.rcd_type is not None and type(self.rcd_type) is not int:
            raise ValueError("rcd_type must be an int or None")
        for field_name, value in (
            ("page_size", self.page_size),
            ("max_pages_per_condition", self.max_pages_per_condition),
            ("max_attempts_per_page", self.max_attempts_per_page),
        ):
            if type(value) is not int:
                raise ValueError(f"{field_name} must be an exact integer")
        if type(self.require_empty_confirmation) is not bool:
            raise ValueError("require_empty_confirmation must be an exact boolean")
        for field_name, (actual, expected) in locked_values.items():
            if actual != expected:
                raise ValueError(f"{field_name} must equal the locked candidate value")
        if _SHA256_RE.fullmatch(self.source_artifact_hash) is None:
            raise ValueError("source_artifact_hash must be a lowercase SHA-256")
        if not isinstance(self.rejected_variants, tuple) or any(
            not isinstance(item, dict) for item in self.rejected_variants
        ):
            raise ValueError("rejected_variants must be a tuple of dictionaries")
        try:
            normalized_rejections = tuple(
                json.loads(
                    json.dumps(
                        item,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
                for item in self.rejected_variants
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("rejected_variants must be canonical JSON values") from exc
        object.__setattr__(self, "rejected_variants", normalized_rejections)

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "rcd_type": self.rcd_type,
            "category_ids": list(self.category_ids),
            "page_size": self.page_size,
            "max_pages_per_condition": self.max_pages_per_condition,
            "require_empty_confirmation": self.require_empty_confirmation,
            "max_attempts_per_page": self.max_attempts_per_page,
            "retry_delays_seconds": list(self.retry_delays_seconds),
            "page_delay_range_seconds": list(self.page_delay_range_seconds),
            "session_mode": self.session_mode,
            "fixed_repeat_category_ids": list(self.fixed_repeat_category_ids),
            "source_artifact_hash": self.source_artifact_hash,
            "rejected_variants": [deepcopy(item) for item in self.rejected_variants],
        }

    @property
    def candidate_hash(self) -> str:
        canonical = json.dumps(
            self._canonical_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {
            **self._canonical_payload(),
            "candidate_hash": self.candidate_hash,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "CensusCandidate":
        expected_keys = {
            "endpoint",
            "rcd_type",
            "category_ids",
            "page_size",
            "max_pages_per_condition",
            "require_empty_confirmation",
            "max_attempts_per_page",
            "retry_delays_seconds",
            "page_delay_range_seconds",
            "session_mode",
            "fixed_repeat_category_ids",
            "source_artifact_hash",
            "rejected_variants",
            "candidate_hash",
        }
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError("candidate payload fields do not match the contract")
        candidate = cls(
            endpoint=payload["endpoint"],
            rcd_type=payload["rcd_type"],
            category_ids=tuple(payload["category_ids"]),
            page_size=payload["page_size"],
            max_pages_per_condition=payload["max_pages_per_condition"],
            require_empty_confirmation=payload["require_empty_confirmation"],
            max_attempts_per_page=payload["max_attempts_per_page"],
            retry_delays_seconds=tuple(payload["retry_delays_seconds"]),
            page_delay_range_seconds=tuple(payload["page_delay_range_seconds"]),
            session_mode=payload["session_mode"],
            fixed_repeat_category_ids=tuple(payload["fixed_repeat_category_ids"]),
            source_artifact_hash=payload["source_artifact_hash"],
            rejected_variants=tuple(payload["rejected_variants"]),
        )
        if payload["candidate_hash"] != candidate.candidate_hash:
            raise ValueError("candidate_hash does not match the canonical payload")
        return candidate


@dataclass(frozen=True, slots=True)
class DetailSmokeTarget:
    position: int
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 1:
            raise ValueError("position must be a positive exact integer")
        OfferTodayDetailIdentity(
            job_id=self.job_id,
            encrypted_job_id=self.encrypted_job_id,
            encrypted_job_id_source=self.encrypted_job_id_source,
        )

    def to_payload(self) -> dict[str, Any]:
        identity_payload = {
            "job_id": self.job_id,
            "encrypted_job_id": self.encrypted_job_id,
            "encrypted_job_id_source": self.encrypted_job_id_source,
        }
        identity_canonical = json.dumps(
            identity_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "position": self.position,
            **identity_payload,
            "job_id_hash": hashlib.sha256(self.job_id.encode()).hexdigest(),
            "encrypted_job_id_hash": hashlib.sha256(
                self.encrypted_job_id.encode()
            ).hexdigest(),
            "identity_resolution_hash": hashlib.sha256(
                identity_canonical.encode()
            ).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class DetailSmokeObservation:
    target: DetailSmokeTarget
    classification: str
    api_code: int | None
    started_at: str
    completed_at: str
    latency_ms: int
    identity_valid: bool
    parsed: bool
    has_title: bool
    has_company: bool
    has_description: bool
    stop_batch: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "target": self.target.to_payload(),
            "classification": self.classification,
            "api_code": self.api_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "identity_valid": self.identity_valid,
            "parsed": self.parsed,
            "has_title": self.has_title,
            "has_company": self.has_company,
            "has_description": self.has_description,
            "stop_batch": self.stop_batch,
        }


@dataclass(frozen=True, slots=True)
class SmokeDecision:
    smoke_passed: bool
    stop_reason: str | None
    expected_truncation: bool
    frozen_count: int
    attempted_count: int
    terminal_count: int
    success_count: int
    unattempted_count: int


@dataclass(frozen=True, slots=True)
class LiveSmokeExecution:
    listing_result: ListingRunResult
    frozen_targets: tuple[DetailSmokeTarget, ...]
    detail_observations: tuple[DetailSmokeObservation, ...]
    decision: SmokeDecision
    would_stage_rows: int
    stage_calls: int
