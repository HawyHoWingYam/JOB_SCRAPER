from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.sources.offertoday.detail_identity import (
    OfferTodayIdentityError,
    read_offertoday_identity_evidence,
    resolve_offertoday_detail_identity,
)
from app.sources.offertoday.research.contracts import (
    CrawlJobEvidenceSnapshot,
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


def extract_snapshot_encrypted_job_id(
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    if not isinstance(listing_payload, Mapping):
        return None
    try:
        return read_offertoday_identity_evidence(
            listing_payload,
            field_names=("encrypted_job_id", "encryptJobId"),
            raw_field_name="encryptJobId",
            evidence_name="encryptJobId",
            required=False,
        )
    except OfferTodayIdentityError:
        return None


def extract_snapshot_identity_error(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    try:
        resolve_offertoday_detail_identity(
            source_job_id=source_job_id,
            listing_payload=listing_payload,
        )
    except OfferTodayIdentityError as exc:
        return str(exc)
    return None


def _identity_alias_values(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
) -> tuple[set[str], bool]:
    values = [payload.get(field_name) for field_name in field_names]
    raw_data = payload.get("raw_data")
    if isinstance(raw_data, Mapping):
        values.append(raw_data.get(raw_field_name))
    valid_values: set[str] = set()
    invalid_value = False
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            invalid_value = True
            continue
        valid_values.add(value.strip())
    return valid_values, invalid_value


def classify_snapshot_identity_error(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    if not isinstance(source_job_id, str) or not source_job_id.strip():
        return "invalid_source_job_id"
    canonical_source_job_id = source_job_id.strip()
    if not isinstance(listing_payload, Mapping):
        return "missing_listing_payload"

    job_ids, invalid_job_id = _identity_alias_values(
        listing_payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
    )
    if invalid_job_id:
        return "invalid_job_id_evidence"
    if not job_ids:
        return "missing_job_id"
    if len(job_ids) > 1:
        return "job_id_alias_conflict"
    if next(iter(job_ids)) != canonical_source_job_id:
        return "source_job_id_mismatch"

    encrypted_job_ids, invalid_encrypted_job_id = _identity_alias_values(
        listing_payload,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
    )
    if invalid_encrypted_job_id:
        return "invalid_encrypted_job_id_evidence"
    if not encrypted_job_ids:
        return "missing_encrypted_job_id"
    if len(encrypted_job_ids) > 1:
        return "encrypted_job_id_alias_conflict"
    return None


def classify_persisted_detail_error(row: Any) -> str | None:
    status = str(getattr(row, "detail_status", "") or "").strip().lower()
    if status in {
        "terminal_unavailable",
        "identity_conflict",
        "manual_action_required",
        "persist_failure",
    }:
        return status
    if status != "failed":
        return None
    error_message = str(
        getattr(row, "detail_error_message", "") or ""
    ).strip().lower()
    if error_message.startswith("persist_failure:"):
        return "persist_failure"
    return "retryable_failed"


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _copy_json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return deepcopy(dict(value))


def _to_crawl_job_evidence_snapshot(row: CrawlJob) -> CrawlJobEvidenceSnapshot:
    return CrawlJobEvidenceSnapshot(
        crawl_job_id=str(row.id),
        status=str(row.status),
        request_payload=_copy_json_mapping(row.request_payload),
        metrics=_copy_json_mapping(row.metrics),
        error_message=(str(row.error_message) if row.error_message else None),
        started_at=_isoformat(row.started_at),
        completed_at=_isoformat(row.completed_at),
    )


class OfferTodayResearchRepository:
    """Read-only OfferToday evidence queries for offline research reports."""

    def list_staged_snapshots(
        self,
        db: Session,
    ) -> list[StagedListingSnapshot]:
        with db.no_autoflush:
            rows = (
                db.query(CrawlJobListing)
                .filter(CrawlJobListing.source_site == "offertoday")
                .order_by(
                    CrawlJobListing.created_at.asc(),
                    CrawlJobListing.id.asc(),
                )
                .all()
            )
        return [
            StagedListingSnapshot(
                row_id=str(row.id),
                source_job_id=str(row.source_job_id),
                detail_status=str(row.detail_status),
                published_job_id=(
                    str(row.published_job_id) if row.published_job_id else None
                ),
                crawl_job_id=str(row.crawl_job_id),
                detail_attempts=int(row.detail_attempts or 0),
                detail_started_at=_isoformat(row.detail_started_at),
                updated_at=_isoformat(row.updated_at),
                encrypted_job_id=extract_snapshot_encrypted_job_id(
                    row.listing_payload
                ),
                identity_error=extract_snapshot_identity_error(
                    source_job_id=row.source_job_id,
                    listing_payload=row.listing_payload,
                ),
                identity_error_classification=classify_snapshot_identity_error(
                    source_job_id=row.source_job_id,
                    listing_payload=row.listing_payload,
                ),
                detail_error_classification=classify_persisted_detail_error(
                    row
                ),
                last_detail_crawl_job_id=(
                    str(row.last_detail_crawl_job_id)
                    if row.last_detail_crawl_job_id
                    else None
                ),
                has_detail_payload=isinstance(row.detail_payload, Mapping),
            )
            for row in rows
        ]

    def list_published_snapshots(
        self,
        db: Session,
    ) -> list[PublishedJobSnapshot]:
        with db.no_autoflush:
            rows = (
                db.query(
                    Job.id,
                    Job.source_job_id,
                    Job.title,
                    Job.company_id,
                    Job.description,
                )
                .filter(
                    Job.source_site == "offertoday",
                    Job.is_deleted.is_(False),
                )
                .all()
            )
        return [
            PublishedJobSnapshot(
                job_id=str(row.id),
                source_job_id=str(row.source_job_id),
                has_title=bool(str(row.title or "").strip()),
                has_company=row.company_id is not None,
                has_description=bool(str(row.description or "").strip()),
            )
            for row in rows
        ]

    def list_research_events(
        self,
        db: Session,
        crawl_job_id: Any,
    ) -> list[CrawlJobEvent]:
        with db.no_autoflush:
            return (
                db.query(CrawlJobEvent)
                .filter(CrawlJobEvent.crawl_job_id == crawl_job_id)
                .order_by(CrawlJobEvent.sequence_no.asc())
                .all()
            )

    def get_crawl_job(
        self,
        db: Session,
        crawl_job_id: Any,
    ) -> CrawlJob | None:
        with db.no_autoflush:
            return (
                db.query(CrawlJob)
                .filter(CrawlJob.id == crawl_job_id)
                .one_or_none()
            )

    def list_recent_crawl_jobs(
        self,
        db: Session,
        *,
        limit: int = 10,
    ) -> list[CrawlJobEvidenceSnapshot]:
        with db.no_autoflush:
            rows = (
                db.query(CrawlJob)
                .filter(CrawlJob.source_site == "offertoday")
                .order_by(CrawlJob.created_at.desc(), CrawlJob.id.desc())
                .limit(max(int(limit), 0))
                .all()
            )
        return [_to_crawl_job_evidence_snapshot(row) for row in rows]
