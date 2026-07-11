from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.sources.offertoday.detail_identity import (
    OfferTodayEncryptedJobIdSource,
    OfferTodayIdentityError,
    read_offertoday_identity_evidence,
    resolve_offertoday_detail_identity,
)
from app.sources.offertoday.research.contracts import (
    CrawlJobEvidenceSnapshot,
    ProductDataSnapshot,
    PublishedJobSnapshot,
    StagedListingSnapshot,
)


def extract_snapshot_observed_encrypted_job_id(
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    if not isinstance(listing_payload, Mapping):
        return None
    try:
        return read_offertoday_identity_evidence(
            listing_payload,
            field_names=("encryptJobId",),
            raw_field_name="encryptJobId",
            evidence_name="encryptJobId",
            required=False,
        )
    except OfferTodayIdentityError:
        return None


@dataclass(frozen=True, slots=True)
class _SnapshotIdentityProjection:
    encrypted_job_id: str | None
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None
    observed_encrypted_job_id: str | None
    identity_error: str | None
    identity_error_classification: str | None


def _project_snapshot_identity(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any] | Any,
) -> _SnapshotIdentityProjection:
    observed_encrypted_job_id = extract_snapshot_observed_encrypted_job_id(
        listing_payload
    )
    try:
        identity = resolve_offertoday_detail_identity(
            source_job_id=source_job_id,
            listing_payload=listing_payload,
        )
    except OfferTodayIdentityError as exc:
        return _SnapshotIdentityProjection(
            encrypted_job_id=None,
            encrypted_job_id_source=None,
            observed_encrypted_job_id=observed_encrypted_job_id,
            identity_error=str(exc),
            identity_error_classification=exc.classification,
        )
    return _SnapshotIdentityProjection(
        encrypted_job_id=identity.encrypted_job_id,
        encrypted_job_id_source=identity.encrypted_job_id_source,
        observed_encrypted_job_id=observed_encrypted_job_id,
        identity_error=None,
        identity_error_classification=None,
    )


def extract_snapshot_identity_error(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    return _project_snapshot_identity(
        source_job_id=source_job_id,
        listing_payload=listing_payload,
    ).identity_error


def classify_snapshot_identity_error(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any] | Any,
) -> str | None:
    return _project_snapshot_identity(
        source_job_id=source_job_id,
        listing_payload=listing_payload,
    ).identity_error_classification


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


def _canonical_database_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_database_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_database_value(item) for item in value]
    raise TypeError(f"unsupported product snapshot value: {type(value).__name__}")


def _hash_table_rows(rows: list[Any], columns: tuple[Any, ...]) -> str:
    payload = {
        "columns": [str(column.name) for column in columns],
        "rows": [
            [
                _canonical_database_value(row._mapping[column])
                for column in columns
            ]
            for row in rows
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _detail_payload_is_object_expression(dialect_name: str):
    json_type = func.json_type if dialect_name == "sqlite" else func.json_typeof
    return (json_type(CrawlJobListing.detail_payload) == "object").label(
        "has_detail_payload"
    )


def _to_staged_listing_snapshot(row: Any) -> StagedListingSnapshot:
    identity = _project_snapshot_identity(
        source_job_id=row.source_job_id,
        listing_payload=row.listing_payload,
    )
    return StagedListingSnapshot(
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
        encrypted_job_id=identity.encrypted_job_id,
        encrypted_job_id_source=identity.encrypted_job_id_source,
        observed_encrypted_job_id=identity.observed_encrypted_job_id,
        identity_error=identity.identity_error,
        identity_error_classification=(
            identity.identity_error_classification
        ),
        detail_error_classification=classify_persisted_detail_error(row),
        last_detail_crawl_job_id=(
            str(row.last_detail_crawl_job_id)
            if row.last_detail_crawl_job_id
            else None
        ),
        has_detail_payload=bool(row.has_detail_payload),
    )


class OfferTodayResearchRepository:
    """Read-only OfferToday evidence queries for offline research reports."""

    def list_staged_snapshots(
        self,
        db: Session,
    ) -> list[StagedListingSnapshot]:
        dialect_name = str(db.get_bind().dialect.name)
        has_detail_payload = _detail_payload_is_object_expression(dialect_name)
        with db.no_autoflush:
            rows = (
                db.query(
                    CrawlJobListing.id,
                    CrawlJobListing.source_job_id,
                    CrawlJobListing.detail_status,
                    CrawlJobListing.published_job_id,
                    CrawlJobListing.crawl_job_id,
                    CrawlJobListing.detail_attempts,
                    CrawlJobListing.detail_started_at,
                    CrawlJobListing.updated_at,
                    CrawlJobListing.listing_payload,
                    CrawlJobListing.detail_error_message,
                    CrawlJobListing.last_detail_crawl_job_id,
                    has_detail_payload,
                )
                .filter(CrawlJobListing.source_site == "offertoday")
                .order_by(
                    CrawlJobListing.created_at.asc(),
                    CrawlJobListing.id.asc(),
                )
                .all()
            )
        return [_to_staged_listing_snapshot(row) for row in rows]

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

    def capture_product_data_snapshot(
        self,
        db: Session,
    ) -> ProductDataSnapshot:
        staging_columns = tuple(CrawlJobListing.__table__.columns)
        job_columns = tuple(Job.__table__.columns)
        company_columns = tuple(Company.__table__.columns)
        referenced_company_ids = select(Job.company_id).where(
            Job.source_site == "offertoday"
        )
        with db.no_autoflush:
            staged_rows = (
                db.query(*staging_columns)
                .filter(CrawlJobListing.source_site == "offertoday")
                .order_by(CrawlJobListing.id.asc())
                .all()
            )
            published_jobs = (
                db.query(*job_columns)
                .filter(Job.source_site == "offertoday")
                .order_by(Job.id.asc())
                .all()
            )
            companies = (
                db.query(*company_columns)
                .filter(
                    or_(
                        Company.source_site == "offertoday",
                        Company.id.in_(referenced_company_ids),
                    )
                )
                .order_by(Company.id.asc())
                .all()
            )
        return ProductDataSnapshot.from_table_hashes(
            staged_rows_hash=_hash_table_rows(staged_rows, staging_columns),
            published_jobs_hash=_hash_table_rows(published_jobs, job_columns),
            companies_hash=_hash_table_rows(companies, company_columns),
        )

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
