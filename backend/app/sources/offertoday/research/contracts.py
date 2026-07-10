from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    run_id: str
    experiment: str
    variant: str
    planner_version: str

    def to_request_payload(self) -> dict[str, Any]:
        return {
            "research": {
                "run_id": self.run_id,
                "experiment": self.experiment,
                "variant": self.variant,
                "planner_version": self.planner_version,
            }
        }


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
    identity_mapping_conflict_ids: tuple[str, ...]
    identity_evidence_conflict_ids: tuple[str, ...]
    identity_error_classifications: dict[str, int]
    detail_status_rows: dict[str, int]
    detail_error_classifications: dict[str, int]
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
