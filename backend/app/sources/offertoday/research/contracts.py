from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.sources.offertoday.detail_identity import (
    OfferTodayEncryptedJobIdSource,
)


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    run_id: str
    experiment: str
    variant: str
    planner_version: str
    plan: int | None = None
    parent_artifact_hash: str | None = None
    request_budget: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.plan is not None and (type(self.plan) is not int or self.plan < 1):
            raise ValueError("plan must be a positive exact integer")
        if self.parent_artifact_hash is not None and not re.fullmatch(
            r"[0-9a-f]{64}",
            self.parent_artifact_hash,
        ):
            raise ValueError("parent_artifact_hash must be lowercase SHA-256")
        if self.request_budget is not None:
            for key, value in self.request_budget.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(
                        "request budget keys must be nonblank strings"
                    )
                if type(value) is not int or value < 0:
                    raise ValueError(
                        "request budget values must be non-negative exact integers"
                    )

    def to_request_payload(self) -> dict[str, Any]:
        research: dict[str, Any] = {
            "run_id": self.run_id,
            "experiment": self.experiment,
            "variant": self.variant,
            "planner_version": self.planner_version,
        }
        if self.plan is not None:
            research["plan"] = int(self.plan)
        if self.parent_artifact_hash is not None:
            research["parent_artifact_hash"] = self.parent_artifact_hash
        if self.request_budget is not None:
            research["request_budget"] = {
                str(key): int(value)
                for key, value in sorted(self.request_budget.items())
            }
        return {"research": research}


@dataclass(frozen=True, slots=True)
class ResearchRunStartInventory:
    published_job_ids: tuple[str, ...]
    staged_unpublished_job_ids: tuple[str, ...]
    data_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "published_job_ids": list(self.published_job_ids),
            "staged_unpublished_job_ids": list(self.staged_unpublished_job_ids),
            "data_hash": self.data_hash,
        }


@dataclass(frozen=True, slots=True)
class StagedListingSnapshot:
    row_id: str
    source_job_id: str
    detail_status: str
    published_job_id: str | None
    crawl_job_id: str
    detail_attempts: int = 0
    detail_started_at: str | None = None
    updated_at: str | None = None
    encrypted_job_id: str | None = None
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None = None
    observed_encrypted_job_id: str | None = None
    identity_error: str | None = None
    identity_error_classification: str | None = None
    detail_error_classification: str | None = None
    last_detail_crawl_job_id: str | None = None
    has_detail_payload: bool = False


@dataclass(frozen=True, slots=True)
class PublishedJobSnapshot:
    job_id: str
    source_job_id: str
    has_title: bool
    has_company: bool
    has_description: bool

    @property
    def is_complete(self) -> bool:
        return self.has_title and self.has_company and self.has_description


@dataclass(frozen=True, slots=True)
class ProductDataSnapshot:
    staged_rows_hash: str
    published_jobs_hash: str
    companies_hash: str
    data_hash: str

    @classmethod
    def from_table_hashes(
        cls,
        *,
        staged_rows_hash: str,
        published_jobs_hash: str,
        companies_hash: str,
    ) -> ProductDataSnapshot:
        table_hashes = {
            "companies_hash": companies_hash,
            "published_jobs_hash": published_jobs_hash,
            "staged_rows_hash": staged_rows_hash,
        }
        for field_name, value in table_hashes.items():
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{field_name} must be lowercase SHA-256")
        canonical = json.dumps(
            table_hashes,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            **table_hashes,
            data_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class BaselineSnapshot:
    staged_rows: int
    distinct_staged_ids: int
    invalid_source_job_id_rows: int
    published_jobs: int
    distinct_staged_unpublished_ids: int
    pending_rows: int
    distinct_pending_ids: int
    pending_rows_with_published_job: int
    distinct_published_ids_with_pending_rows: int
    published_partial_jobs: int
    duplicate_staging_rows: int
    missing_encrypted_job_id_rows: int
    observed_encrypted_job_id_rows: int
    job_id_fallback_rows: int
    unusable_identity_rows: int
    identity_mapping_conflict_ids: tuple[str, ...]
    identity_evidence_conflict_ids: tuple[str, ...]
    identity_error_classifications: dict[str, int]
    detail_status_rows: dict[str, int]
    detail_error_classifications: dict[str, int]
    staged_rows_hash: str
    published_jobs_hash: str
    companies_hash: str
    product_data_hash: str
    data_hash: str


@dataclass(frozen=True, slots=True)
class CrawlJobEvidenceSnapshot:
    crawl_job_id: str
    status: str
    request_payload: dict[str, Any]
    metrics: dict[str, Any]
    error_message: str | None
    started_at: str | None
    completed_at: str | None
