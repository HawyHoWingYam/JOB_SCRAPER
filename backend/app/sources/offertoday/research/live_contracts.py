from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.sources.offertoday.listing_runner import ListingRunResult


@dataclass(frozen=True, slots=True)
class DetailSmokeTarget:
    position: int
    job_id: str
    encrypted_job_id: str

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 1:
            raise ValueError("position must be a positive exact integer")
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("job_id must be a nonblank string")
        if (
            not isinstance(self.encrypted_job_id, str)
            or not self.encrypted_job_id.strip()
        ):
            raise ValueError("encrypted_job_id must be a nonblank string")

    def to_payload(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "job_id": self.job_id,
            "encrypted_job_id": self.encrypted_job_id,
            "job_id_hash": hashlib.sha256(self.job_id.encode()).hexdigest(),
            "encrypted_job_id_hash": hashlib.sha256(
                self.encrypted_job_id.encode()
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
