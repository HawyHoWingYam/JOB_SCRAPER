from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
)
from app.sources.offertoday.listing_runner import ListingRunResult

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CENSUS_CATEGORY_IDS = tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
_FIXED_REPEAT_CATEGORY_IDS = (118000, 112000, 127000)


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
