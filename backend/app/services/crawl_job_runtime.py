from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.crawl_phases import DEFAULT_DETAIL_RETRY_STATUSES
from app.database import SessionLocal
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.crawl_job_repository import CrawlJobRepository, _UNSET as CRAWL_JOB_REPOSITORY_UNSET
from app.repositories.job_repository import JobRepository
from app.sources.offertoday.completeness import is_complete_offertoday_job
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayIdentityError,
    build_offertoday_identity_authority_index,
    resolve_offertoday_detail_identity,
)
from app.sources.offertoday.search_space import (
    resolve_offertoday_detail_category_ids,
)
from app.utils.time import utc_now

_UNSET = CRAWL_JOB_REPOSITORY_UNSET


@dataclass(frozen=True)
class ListingBatchPersistResult:
    rows_created: int
    created_source_job_ids: tuple[str, ...]
    preexisting_staged_source_job_ids: tuple[str, ...]
    published_source_job_ids: tuple[str, ...]
    job_ids_seen: int
    skipped_existing: int

    @property
    def rows_staged(self) -> int:
        """Compatibility alias for callers that still use the staging-era name."""

        return self.rows_created


@dataclass(frozen=True)
class DetailTargetLoadResult:
    target_rows: int
    selected_rows: int
    skipped_existing_rows: int
    distinct_selected_ids: int
    reconciled_rows: int
    duplicate_rows: int
    fetch_cohort_source_job_ids: tuple[str, ...]
    fetch_cohort_hash: str
    reconciled_source_job_ids: tuple[str, ...]
    identity_conflict_ids: tuple[str, ...]
    identity_conflict_evidence: tuple[dict[str, Any], ...]
    reconciliation_records: tuple[dict[str, Any], ...]
    targets: list[dict[str, Any]]


def _canonical_id_hash(source_job_ids: tuple[str, ...]) -> str:
    canonical_json = json.dumps(
        source_job_ids,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _group_detail_rows(selected_rows: list[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for row in selected_rows:
        source_job_id = str(getattr(row, "source_job_id", "") or "").strip()
        if source_job_id:
            groups.setdefault(source_job_id, []).append(row)
    return groups


def _audit_offertoday_detail_identities(
    *,
    identity_history: list[Any],
    identity_observations: list[dict[str, Any]],
    selected_rows: list[Any],
    groups: dict[str, list[Any]],
) -> tuple[
    dict[Any, OfferTodayDetailIdentity],
    dict[str, OfferTodayDetailIdentity],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, str],
    tuple[dict[str, str], ...],
]:
    selected_row_ids = {row.id for row in selected_rows}
    resolved_identity_by_row_id: dict[Any, OfferTodayDetailIdentity] = {}
    all_identities: list[OfferTodayDetailIdentity] = []
    unusable_job_ids: set[str] = set()

    def add_identity(identity: OfferTodayDetailIdentity) -> None:
        all_identities.append(identity)

    for history_row in identity_history:
        source_job_id = str(
            getattr(history_row, "source_job_id", "") or ""
        ).strip()
        history_payload = getattr(history_row, "listing_payload", None)
        try:
            identity = resolve_offertoday_detail_identity(
                source_job_id=source_job_id,
                listing_payload=(
                    dict(history_payload)
                    if isinstance(history_payload, Mapping)
                    else {}
                ),
            )
        except OfferTodayIdentityError:
            if source_job_id:
                unusable_job_ids.add(source_job_id)
            continue
        add_identity(identity)
        if history_row.id in selected_row_ids:
            resolved_identity_by_row_id[history_row.id] = identity

    for observation in identity_observations:
        source_job_id = str(observation.get("source_job_id") or "").strip()
        try:
            identity = resolve_offertoday_detail_identity(
                source_job_id=source_job_id,
                listing_payload=observation,
            )
        except OfferTodayIdentityError:
            if source_job_id:
                unusable_job_ids.add(source_job_id)
            continue
        add_identity(identity)

    authority_index = build_offertoday_identity_authority_index(
        tuple(all_identities)
    )
    authoritative_identity_by_job = dict(
        authority_index.authoritative_identity_by_job
    )
    explicit_ids_by_job = {
        job_id: set(route_ids)
        for job_id, route_ids in authority_index.explicit_ids_by_job.items()
    }
    route_to_job_ids = {
        route_id: set(job_ids)
        for route_id, job_ids in authority_index.route_to_job_ids.items()
    }

    conflict_reason_by_job: dict[str, str] = {}
    for source_job_id, rows in groups.items():
        selected_identities = [
            resolved_identity_by_row_id.get(row.id) for row in rows
        ]
        if source_job_id in authority_index.conflict_reason_by_job:
            conflict_reason_by_job[source_job_id] = (
                authority_index.conflict_reason_by_job[source_job_id]
            )
            continue
        if (
            source_job_id in unusable_job_ids
            or any(identity is None for identity in selected_identities)
            or source_job_id not in authoritative_identity_by_job
        ):
            conflict_reason_by_job[source_job_id] = "unusable_identity_evidence"
            continue
        authority = authoritative_identity_by_job[source_job_id]
        if len(route_to_job_ids.get(authority.encrypted_job_id, set())) > 1:
            conflict_reason_by_job[source_job_id] = "reverse_collision"

    provenance_upgrades = tuple(
        {
            "source_job_id": source_job_id,
            "encrypted_job_id": authoritative_identity_by_job[
                source_job_id
            ].encrypted_job_id,
            "from_source": "jobId_fallback",
            "to_source": "encryptJobId",
        }
        for source_job_id in groups
        if source_job_id not in conflict_reason_by_job
        and source_job_id in authority_index.fallback_job_ids
        and authoritative_identity_by_job[source_job_id].encrypted_job_id_source
        == "encryptJobId"
    )

    return (
        resolved_identity_by_row_id,
        authoritative_identity_by_job,
        explicit_ids_by_job,
        route_to_job_ids,
        conflict_reason_by_job,
        provenance_upgrades,
    )


def _build_identity_conflict_evidence(
    *,
    conflict_reason_by_job: dict[str, str],
    explicit_ids_by_job: dict[str, set[str]],
    authoritative_identity_by_job: dict[str, OfferTodayDetailIdentity],
    route_to_job_ids: dict[str, set[str]],
) -> list[dict[str, Any]]:
    evidence_records: list[dict[str, Any]] = []
    for source_job_id in sorted(conflict_reason_by_job):
        authority = authoritative_identity_by_job.get(source_job_id)
        reverse_peer_job_ids = (
            sorted(
                route_to_job_ids.get(authority.encrypted_job_id, set())
                - {source_job_id}
            )
            if authority is not None
            else []
        )
        evidence_records.append(
            {
                "source_job_id": source_job_id,
                "encrypted_job_ids": sorted(
                    explicit_ids_by_job.get(source_job_id, set())
                ),
                "reverse_peer_job_ids": reverse_peer_job_ids,
                "reason": conflict_reason_by_job[source_job_id],
            }
        )
    return evidence_records


class CrawlJobRuntime:
    def __init__(
        self,
        db_session_factory=SessionLocal,
        *,
        crawl_job_repository: CrawlJobRepository | None = None,
        crawl_job_listing_repository: CrawlJobListingRepository | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self.session_factory = db_session_factory
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.crawl_job_listing_repository = crawl_job_listing_repository or CrawlJobListingRepository()
        self.job_repository = job_repository or JobRepository()

    def write_progress_event(
        self,
        *,
        crawl_job_id,
        event_type: str,
        payload: dict[str, Any],
        emitted_by: str,
    ) -> None:
        db = self.session_factory()
        try:
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=crawl_job_id,
                event_type=event_type,
                payload=dict(payload or {}),
                emitted_by=emitted_by,
                auto_commit=True,
            )
        finally:
            db.close()

    def merge_metrics(
        self,
        *,
        crawl_job_id,
        metrics_patch: dict[str, Any],
    ) -> None:
        db = self.session_factory()
        try:
            self.crawl_job_repository.merge_metrics(
                db,
                crawl_job_id=crawl_job_id,
                metrics_patch=dict(metrics_patch or {}),
                auto_commit=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_started(
        self,
        *,
        crawl_job_id,
        source_site: str,
        payload: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        emitted_by: str | None = None,
    ) -> None:
        self._record_runtime_event(
            crawl_job_id=crawl_job_id,
            status="running",
            event_type="crawl.started",
            payload={
                "source_site": str(source_site).strip().lower(),
                **dict(payload or {}),
            },
            emitted_by=emitted_by or f"{source_site}-crawl",
            started_at=utc_now(),
            completed_at=None,
            error_message=None,
            metrics=metrics or {},
        )

    def mark_completed(
        self,
        *,
        crawl_job_id,
        source_site: str,
        payload: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        emitted_by: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._record_runtime_event(
            crawl_job_id=crawl_job_id,
            status="completed",
            event_type="crawl.completed",
            payload=dict(payload or {}),
            emitted_by=emitted_by or f"{source_site}-crawl",
            completed_at=utc_now(),
            error_message=error_message,
            metrics=metrics or {},
        )

    def mark_failed(
        self,
        *,
        crawl_job_id,
        source_site: str,
        error_message: str,
        payload: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        emitted_by: str | None = None,
    ) -> None:
        failure_payload = dict(payload or {})
        failure_payload.setdefault("error", error_message)
        self._record_runtime_event(
            crawl_job_id=crawl_job_id,
            status="failed",
            event_type="crawl.failed",
            payload=failure_payload,
            emitted_by=emitted_by or f"{source_site}-crawl",
            completed_at=utc_now(),
            error_message=error_message,
            metrics=metrics or {},
        )

    def stage_listing_batch(
        self,
        *,
        crawl_job_id,
        source_site: str,
        payloads: list[dict[str, Any]],
        skip_existing: bool,
    ) -> ListingBatchPersistResult:
        db = self.session_factory()
        try:
            normalized_source = str(source_site).strip().lower()
            batch_payloads = [dict(payload or {}) for payload in payloads]
            ordered_job_ids = self._ordered_distinct_source_job_ids(batch_payloads)
            seen_job_ids = set(ordered_job_ids)
            is_offertoday = normalized_source == "offertoday"
            if is_offertoday:
                self.crawl_job_listing_repository.acquire_offertoday_staging_lock(db)

            existing_jobs_by_source_id = (
                self.job_repository.list_existing_jobs_by_source_ids(
                    db,
                    source_site=normalized_source,
                    source_job_ids=ordered_job_ids,
                    raise_on_error=is_offertoday,
                )
                if (is_offertoday or skip_existing) and seen_job_ids
                else {}
            )
            published_source_job_ids = tuple(
                source_job_id
                for source_job_id in ordered_job_ids
                if source_job_id in existing_jobs_by_source_id
            )
            published_source_job_id_set = set(published_source_job_ids)
            preexisting_staged_source_job_ids: tuple[str, ...] = ()
            if is_offertoday and seen_job_ids:
                staged_source_job_ids = (
                    self.crawl_job_listing_repository.list_existing_source_job_ids(
                        db,
                        source_site=normalized_source,
                        source_job_ids=ordered_job_ids,
                    )
                )
                preexisting_staged_source_job_ids = tuple(
                    source_job_id
                    for source_job_id in ordered_job_ids
                    if source_job_id in staged_source_job_ids
                    and source_job_id not in published_source_job_id_set
                )
            preexisting_staged_source_job_id_set = set(
                preexisting_staged_source_job_ids
            )
            skipped_existing = 0
            rows_created = 0
            created_source_job_ids: list[str] = []
            created_source_job_id_set: set[str] = set()
            next_rank = self.crawl_job_listing_repository.get_max_listing_rank_for_crawl_job(
                db,
                crawl_job_id=crawl_job_id,
                source_site=normalized_source,
            )

            if is_offertoday:
                first_payload_by_source_job_id = {
                    source_job_id: next(
                        payload
                        for payload in batch_payloads
                        if str(payload.get("source_job_id") or "").strip()
                        == source_job_id
                    )
                    for source_job_id in ordered_job_ids
                }
                payloads_to_stage = [
                    first_payload_by_source_job_id[source_job_id]
                    for source_job_id in ordered_job_ids
                ]
            else:
                payloads_to_stage = batch_payloads

            for payload in payloads_to_stage:
                source_job_id = str(payload.get("source_job_id") or "").strip()
                if not source_job_id:
                    continue
                if source_job_id in published_source_job_id_set and (
                    is_offertoday or skip_existing
                ):
                    skipped_existing += 1
                    continue
                if (
                    is_offertoday
                    and source_job_id in preexisting_staged_source_job_id_set
                ):
                    skipped_existing += 1
                    continue

                next_rank += 1
                listing_rank = (
                    next_rank
                    if is_offertoday
                    else self._optional_int(payload.get("listing_rank")) or next_rank
                )
                _listing, persistence_status = (
                    self.crawl_job_listing_repository.upsert_listing(
                        db,
                        crawl_job_id=crawl_job_id,
                        source_site=normalized_source,
                        source_job_id=source_job_id,
                        source_url=str(payload.get("source_url") or "").strip(),
                        source_classification_id=self._optional_str(
                            payload.get("source_classification_id")
                        ),
                        source_classification_name=self._optional_str(
                            payload.get("source_classification_name")
                        ),
                        listing_page=self._optional_int(payload.get("listing_page")),
                        listing_rank=listing_rank,
                        listing_payload=dict(payload.get("listing_payload") or {}),
                        auto_commit=False,
                    )
                )
                if (
                    persistence_status == "created"
                    and source_job_id not in created_source_job_id_set
                ):
                    rows_created += 1
                    created_source_job_id_set.add(source_job_id)
                    created_source_job_ids.append(source_job_id)

            self._sync_listing_metrics(
                db,
                crawl_job_id=crawl_job_id,
                source_site=normalized_source,
                skipped_existing_delta=skipped_existing,
            )
            if is_offertoday:
                classification_by_source_job_id = {
                    source_job_id: (
                        "published"
                        if source_job_id in published_source_job_id_set
                        else "preexisting_staged_unpublished"
                        if source_job_id in preexisting_staged_source_job_id_set
                        else "newly_staged"
                    )
                    for source_job_id in ordered_job_ids
                }
                self.crawl_job_repository.append_event(
                    db,
                    crawl_job_id=crawl_job_id,
                    event_type="crawl.listing_observed",
                    payload={
                        "source_site": normalized_source,
                        "source_job_ids": ordered_job_ids,
                        "observations": [
                            self._listing_observation_payload(
                                source_job_id=source_job_id,
                                classification=classification_by_source_job_id[source_job_id],
                                payload=input_payload,
                            )
                            for input_payload in batch_payloads
                            if (
                                source_job_id := str(
                                    input_payload.get("source_job_id") or ""
                                ).strip()
                            )
                        ],
                        "published_source_job_ids": list(
                            published_source_job_ids
                        ),
                        "preexisting_staged_source_job_ids": list(
                            preexisting_staged_source_job_ids
                        ),
                        "created_source_job_ids": created_source_job_ids,
                        "rows_created": rows_created,
                        "job_ids_seen": len(ordered_job_ids),
                        "skipped_existing": skipped_existing,
                    },
                    emitted_by="offertoday-crawl",
                    auto_commit=False,
                )
            db.commit()
            return ListingBatchPersistResult(
                rows_created=rows_created,
                created_source_job_ids=tuple(created_source_job_ids),
                preexisting_staged_source_job_ids=preexisting_staged_source_job_ids,
                published_source_job_ids=published_source_job_ids,
                job_ids_seen=len(ordered_job_ids),
                skipped_existing=skipped_existing,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def load_detail_targets(
        self,
        *,
        source_site: str,
        request_payload: dict[str, Any],
        detail_crawl_job_id,
    ) -> DetailTargetLoadResult:
        db = self.session_factory()
        try:
            normalized_source = str(source_site).strip().lower()
            payload = dict(request_payload or {})
            source_job_ids_present = "source_job_ids" in payload
            source_job_ids = (
                self._ordered_distinct_values(payload.get("source_job_ids") or [])
                if source_job_ids_present
                else None
            )
            source_listing_crawl_job_id = (
                None
                if source_job_ids_present
                else payload.get("source_listing_crawl_job_id")
            )
            detail_limit = max(int(payload.get("detail_limit") or 100), 1)
            category_ids = (
                resolve_offertoday_detail_category_ids(
                    payload.get("category_ids") or [],
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                )
                if normalized_source == "offertoday"
                else payload.get("category_ids") or []
            )
            selected_rows = (
                self.crawl_job_listing_repository.list_detail_candidates(
                    db,
                    source_site=normalized_source,
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                    category_ids=category_ids,
                    statuses=payload.get("detail_statuses"),
                    source_job_ids=source_job_ids,
                    limit=None,
                )
                if source_job_ids is None or source_job_ids
                else []
            )
            groups = _group_detail_rows(selected_rows)

            resolved_identity_by_row_id: dict[
                Any, OfferTodayDetailIdentity
            ] = {}
            authoritative_identity_by_job: dict[
                str, OfferTodayDetailIdentity
            ] = {}
            explicit_ids_by_job: dict[str, set[str]] = {}
            route_to_job_ids: dict[str, set[str]] = {}
            conflict_reason_by_job: dict[str, str] = {}
            provenance_upgrades: tuple[dict[str, str], ...] = ()
            if normalized_source == "offertoday" and selected_rows:
                (
                    resolved_identity_by_row_id,
                    authoritative_identity_by_job,
                    explicit_ids_by_job,
                    route_to_job_ids,
                    conflict_reason_by_job,
                    provenance_upgrades,
                ) = _audit_offertoday_detail_identities(
                    identity_history=self.crawl_job_listing_repository.list_offertoday_identity_history(
                        db
                    ),
                    identity_observations=self.crawl_job_repository.list_offertoday_listing_identity_observations(
                        db
                    ),
                    selected_rows=selected_rows,
                    groups=groups,
                )

            identity_conflict_ids = set(conflict_reason_by_job)
            conflict_evidence: list[dict[str, Any]] = []
            if identity_conflict_ids:
                conflict_evidence = _build_identity_conflict_evidence(
                    conflict_reason_by_job=conflict_reason_by_job,
                    explicit_ids_by_job=explicit_ids_by_job,
                    authoritative_identity_by_job=authoritative_identity_by_job,
                    route_to_job_ids=route_to_job_ids,
                )
                evidence_by_source_job_id = {
                    evidence["source_job_id"]: evidence
                    for evidence in conflict_evidence
                }
                for source_job_id in sorted(identity_conflict_ids):
                    evidence = evidence_by_source_job_id[source_job_id]
                    for row in groups[source_job_id]:
                        self.crawl_job_listing_repository.mark_detail_identity_conflict(
                            db,
                            listing_id=row.id,
                            detail_crawl_job_id=detail_crawl_job_id,
                            error_message=(
                                "OfferToday jobId/encryptJobId mapping conflict: "
                                f"{evidence['reason']}"
                            ),
                            auto_commit=False,
                        )

                self.crawl_job_repository.append_event(
                    db,
                    crawl_job_id=detail_crawl_job_id,
                    event_type="crawl.detail_identity_conflict",
                    payload={"conflicts": conflict_evidence},
                    emitted_by="crawl-runtime",
                    auto_commit=False,
                )

            eligible_groups = {
                source_job_id: rows
                for source_job_id, rows in groups.items()
                if source_job_id not in identity_conflict_ids
            }

            if provenance_upgrades:
                self.crawl_job_repository.append_event(
                    db,
                    crawl_job_id=detail_crawl_job_id,
                    event_type="crawl.detail_identity_provenance_upgraded",
                    payload={
                        "upgrades": [dict(item) for item in provenance_upgrades]
                    },
                    emitted_by="crawl-runtime",
                    auto_commit=False,
                )

            existing_jobs_by_source_id = (
                self.job_repository.list_existing_jobs_by_source_ids(
                    db,
                    source_site=normalized_source,
                    source_job_ids=list(eligible_groups),
                )
                if payload.get("skip_existing") and eligible_groups
                else {}
            )
            targets: list[dict[str, Any]] = []
            reconciled_rows = 0
            reconciled_source_job_ids: list[str] = []
            reconciliation_records: list[dict[str, Any]] = []

            for source_job_id, rows in eligible_groups.items():
                existing_job = existing_jobs_by_source_id.get(source_job_id)
                should_reconcile = existing_job is not None and (
                    normalized_source != "offertoday"
                    or is_complete_offertoday_job(existing_job)
                )
                if should_reconcile:
                    for row in rows:
                        before_status = str(
                            getattr(row, "detail_status", "") or ""
                        )
                        self.crawl_job_listing_repository.mark_detail_completed(
                            db,
                            listing_id=row.id,
                            detail_crawl_job_id=detail_crawl_job_id,
                            detail_payload=dict(
                                getattr(existing_job, "raw_data", None) or {}
                            ),
                            published_job_id=getattr(existing_job, "id", None),
                            auto_commit=False,
                        )
                        reconciled_rows += 1
                        reconciliation_records.append(
                            {
                                "listing_id": str(row.id),
                                "source_job_id": source_job_id,
                                "before_status": before_status,
                                "after_status": "completed",
                                "published_job_id": str(existing_job.id),
                            }
                        )
                    reconciled_source_job_ids.append(source_job_id)
                    continue

                authoritative = rows[0]
                targets.append(
                    {
                        "listing_id": authoritative.id,
                        "duplicate_listing_ids": tuple(
                            row.id for row in rows[1:]
                        ),
                        "crawl_job_id": authoritative.crawl_job_id,
                        "source_site": authoritative.source_site,
                        "source_job_id": source_job_id,
                        "source_url": authoritative.source_url,
                        "source_classification_id": authoritative.source_classification_id,
                        "source_classification_name": authoritative.source_classification_name,
                        "listing_payload": dict(
                            getattr(authoritative, "listing_payload", None) or {}
                        ),
                        "detail_payload": dict(
                            getattr(authoritative, "detail_payload", None) or {}
                        ),
                        "identity": (
                            authoritative_identity_by_job[source_job_id]
                            if normalized_source == "offertoday"
                            else None
                        ),
                    }
                )

            targets = targets[:detail_limit]
            if reconciliation_records:
                self.crawl_job_repository.append_event(
                    db,
                    crawl_job_id=detail_crawl_job_id,
                    event_type="crawl.detail_reconciled",
                    payload={"records": reconciliation_records},
                    emitted_by="crawl-runtime",
                    auto_commit=False,
                )

            if source_listing_crawl_job_id is not None:
                self._sync_listing_metrics(
                    db,
                    crawl_job_id=source_listing_crawl_job_id,
                    source_site=normalized_source,
                    skipped_existing_delta=0,
                )
            self._sync_detail_run_metrics(
                db,
                detail_crawl_job_id=detail_crawl_job_id,
                source_site=normalized_source,
                selected_rows=len(selected_rows),
                skipped_existing_rows=reconciled_rows,
                target_rows=len(targets),
                distinct_selected_ids=len(groups),
                reconciled_rows=reconciled_rows,
                duplicate_rows=len(selected_rows) - len(groups),
            )
            fetch_cohort_source_job_ids = tuple(
                target["source_job_id"] for target in targets
            )
            db.commit()
            return DetailTargetLoadResult(
                target_rows=len(targets),
                selected_rows=len(selected_rows),
                skipped_existing_rows=reconciled_rows,
                distinct_selected_ids=len(groups),
                reconciled_rows=reconciled_rows,
                duplicate_rows=len(selected_rows) - len(groups),
                fetch_cohort_source_job_ids=fetch_cohort_source_job_ids,
                fetch_cohort_hash=_canonical_id_hash(
                    fetch_cohort_source_job_ids
                ),
                reconciled_source_job_ids=tuple(reconciled_source_job_ids),
                identity_conflict_ids=tuple(sorted(identity_conflict_ids)),
                identity_conflict_evidence=tuple(conflict_evidence),
                reconciliation_records=tuple(reconciliation_records),
                targets=targets,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def defer_listing_identity_conflict(
        self,
        *,
        crawl_job_id,
        source_job_ids: list[str] | tuple[str, ...],
        encrypted_job_ids: list[str] | tuple[str, ...],
        reason: str,
    ) -> int:
        db = self.session_factory()
        try:
            normalized_source_job_ids = self._ordered_distinct_values(
                source_job_ids,
                max_length=255,
            )
            normalized_encrypted_job_ids = self._ordered_distinct_values(
                encrypted_job_ids,
                max_length=255,
            )
            normalized_reason = str(reason or "").strip()[:500] or "identity_conflict"
            self.crawl_job_listing_repository.acquire_offertoday_staging_lock(db)
            rows_deferred = self.crawl_job_listing_repository.defer_identity_conflicts(
                db,
                source_site="offertoday",
                source_job_ids=normalized_source_job_ids,
                statuses=DEFAULT_DETAIL_RETRY_STATUSES,
                error_message=normalized_reason,
                auto_commit=False,
            )
            self.crawl_job_repository.append_event(
                db,
                crawl_job_id=crawl_job_id,
                event_type="crawl.listing_identity_conflict",
                payload={
                    "source_site": "offertoday",
                    "source_job_ids": normalized_source_job_ids,
                    "encrypted_job_ids": normalized_encrypted_job_ids,
                    "reason": normalized_reason,
                    "rows_deferred": rows_deferred,
                },
                emitted_by="offertoday-crawl",
                auto_commit=False,
            )
            db.commit()
            return rows_deferred
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def transition_detail_running(self, db, *, listing_id, detail_crawl_job_id):
        listing = self.crawl_job_listing_repository.mark_detail_running(
            db,
            listing_id=listing_id,
            detail_crawl_job_id=detail_crawl_job_id,
            auto_commit=False,
        )
        self._sync_detail_group_transition_metrics(
            db,
            listings=(listing,),
            detail_crawl_job_id=detail_crawl_job_id,
        )
        return listing

    def transition_detail_completed(
        self,
        db,
        *,
        listing_ids,
        detail_crawl_job_id,
        detail_payload: dict[str, Any],
        published_job_id=None,
    ):
        listings = tuple(
            self.crawl_job_listing_repository.mark_detail_completed(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                detail_payload=detail_payload,
                published_job_id=published_job_id,
                auto_commit=False,
            )
            for listing_id in listing_ids
        )
        self._sync_detail_group_transition_metrics(
            db,
            listings=listings,
            detail_crawl_job_id=detail_crawl_job_id,
        )
        return listings

    def transition_detail_outcome(
        self,
        db,
        *,
        listing_ids,
        detail_crawl_job_id,
        status: str | None = None,
        error_message: str,
        detail_payload: dict[str, Any] | None = None,
        detail_status: str | None = None,
    ):
        if status is not None and detail_status is not None and status != detail_status:
            raise ValueError("Conflicting detail outcome status values")
        requested_status = status if status is not None else detail_status
        listings = tuple(
            self.crawl_job_listing_repository.mark_detail_outcome(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                status=requested_status,
                error_message=error_message,
                detail_payload=detail_payload,
                auto_commit=False,
            )
            for listing_id in listing_ids
        )
        self._sync_detail_group_transition_metrics(
            db,
            listings=listings,
            detail_crawl_job_id=detail_crawl_job_id,
        )
        return listings

    def record_detail_persisted(
        self,
        db,
        *,
        detail_crawl_job_id,
        source_job_id: str,
        listing_ids,
        published_job_id,
        response_identity_hash: str,
    ):
        return self.crawl_job_repository.append_event(
            db,
            crawl_job_id=detail_crawl_job_id,
            event_type="crawl.detail_persisted",
            payload={
                "detail_crawl_job_id": str(detail_crawl_job_id),
                "source_job_id": str(source_job_id),
                "listing_ids": [str(listing_id) for listing_id in listing_ids],
                "published_job_id": str(published_job_id),
                "response_identity_hash": str(response_identity_hash),
            },
            emitted_by="offertoday-detail-pipeline",
            auto_commit=False,
        )

    def mark_detail_running(self, *, listing_id, detail_crawl_job_id) -> None:
        db = self.session_factory()
        try:
            self.transition_detail_running(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_detail_completed(
        self,
        *,
        listing_id,
        detail_crawl_job_id,
        detail_payload: dict[str, Any],
        published_job_id=None,
    ) -> None:
        db = self.session_factory()
        try:
            self.transition_detail_completed(
                db,
                listing_ids=(listing_id,),
                detail_crawl_job_id=detail_crawl_job_id,
                detail_payload=detail_payload,
                published_job_id=published_job_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_detail_failed(
        self,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message: str,
    ) -> None:
        db = self.session_factory()
        try:
            self.transition_detail_outcome(
                db,
                listing_ids=(listing_id,),
                detail_crawl_job_id=detail_crawl_job_id,
                status="failed",
                error_message=error_message,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_detail_manual_action_required(
        self,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message: str,
    ) -> None:
        db = self.session_factory()
        try:
            self.transition_detail_outcome(
                db,
                listing_ids=(listing_id,),
                detail_crawl_job_id=detail_crawl_job_id,
                status="manual_action_required",
                error_message=error_message,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_manual_action_required(
        self,
        *,
        crawl_job_id,
        source_site: str,
        request_payload: dict[str, Any],
        payload: dict[str, Any],
        error_message: str,
    ) -> None:
        self._record_runtime_event(
            crawl_job_id=crawl_job_id,
            status="manual_action_required",
            event_type="crawl.manual_action_required",
            payload={
                "source_site": str(source_site).strip().lower(),
                "request_payload": dict(request_payload or {}),
                "manual_action": dict(payload or {}),
                "error": error_message,
            },
            emitted_by=f"{source_site}-crawl",
            completed_at=utc_now(),
            error_message=error_message,
        )

    def _record_runtime_event(
        self,
        *,
        crawl_job_id,
        status: str,
        event_type: str,
        payload: dict[str, Any],
        emitted_by: str,
        started_at=_UNSET,
        completed_at=_UNSET,
        error_message=_UNSET,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        db = self.session_factory()
        try:
            self.crawl_job_repository.record_runtime_event(
                db,
                crawl_job_id=crawl_job_id,
                status=status,
                event_type=event_type,
                payload=dict(payload or {}),
                emitted_by=emitted_by,
                started_at=started_at,
                completed_at=completed_at,
                error_message=error_message,
                metrics=metrics,
                auto_commit=True,
            )
        finally:
            db.close()

    def _sync_detail_transition_metrics(self, db, *, listing, detail_crawl_job_id) -> None:
        self._sync_detail_group_transition_metrics(
            db,
            listings=(listing,),
            detail_crawl_job_id=detail_crawl_job_id,
        )

    def _sync_detail_group_transition_metrics(
        self,
        db,
        *,
        listings,
        detail_crawl_job_id,
    ) -> None:
        normalized_listings = tuple(listings)
        listing_batches = {
            (listing.crawl_job_id, listing.source_site)
            for listing in normalized_listings
        }
        for crawl_job_id, source_site in listing_batches:
            self._sync_listing_metrics(
                db,
                crawl_job_id=crawl_job_id,
                source_site=source_site,
                skipped_existing_delta=0,
            )
        for source_site in {listing.source_site for listing in normalized_listings}:
            self._sync_detail_run_metrics(
                db,
                detail_crawl_job_id=detail_crawl_job_id,
                source_site=source_site,
            )

    def _sync_listing_metrics(
        self,
        db,
        *,
        crawl_job_id,
        source_site: str,
        skipped_existing_delta: int,
    ) -> None:
        counts = self.crawl_job_listing_repository.count_detail_statuses(
            db,
            source_site=source_site,
            source_listing_crawl_job_id=crawl_job_id,
        )
        listings_staged = sum(int(value or 0) for value in counts.values())
        crawl_job = self.crawl_job_repository.get_crawl_job_by_id(db, crawl_job_id)
        existing_metrics = dict(getattr(crawl_job, "metrics", None) or {})
        skipped_existing_total = int(existing_metrics.get("jobs_skipped_existing") or 0) + int(
            skipped_existing_delta or 0
        )
        self.crawl_job_repository.merge_metrics(
            db,
            crawl_job_id=crawl_job_id,
            metrics_patch={
                "listings_staged": listings_staged,
                "detail_pending": int(counts.get("pending", 0)),
                "detail_running": int(counts.get("running", 0)),
                "detail_completed": int(counts.get("completed", 0)),
                "detail_failed": int(counts.get("failed", 0)),
                "detail_manual_action_required": int(counts.get("manual_action_required", 0)),
                "detail_terminal_unavailable": int(
                    counts.get("terminal_unavailable", 0)
                ),
                "detail_identity_conflict": int(
                    counts.get("identity_conflict", 0)
                ),
                "jobs_skipped_existing": skipped_existing_total,
            },
            auto_commit=False,
        )

    def _sync_detail_run_metrics(
        self,
        db,
        *,
        detail_crawl_job_id,
        source_site: str,
        selected_rows: int | None = None,
        skipped_existing_rows: int | None = None,
        target_rows: int | None = None,
        distinct_selected_ids: int | None = None,
        reconciled_rows: int | None = None,
        duplicate_rows: int | None = None,
    ) -> None:
        run_counts = self.crawl_job_listing_repository.count_detail_statuses_for_detail_crawl_job(
            db,
            detail_crawl_job_id=detail_crawl_job_id,
            source_site=source_site,
        )
        metrics_patch = {
            "detail_run_completed": int(run_counts.get("completed", 0)),
            "detail_run_failed": int(run_counts.get("failed", 0)),
            "detail_run_manual_action_required": int(run_counts.get("manual_action_required", 0)),
            "detail_run_terminal_unavailable": int(
                run_counts.get("terminal_unavailable", 0)
            ),
            "detail_run_identity_conflict": int(
                run_counts.get("identity_conflict", 0)
            ),
        }
        if selected_rows is not None:
            metrics_patch["detail_selected_rows"] = int(selected_rows)
        if skipped_existing_rows is not None:
            metrics_patch["detail_skipped_existing_rows"] = int(skipped_existing_rows)
        if target_rows is not None:
            metrics_patch["detail_target_rows"] = int(target_rows)
        if distinct_selected_ids is not None:
            metrics_patch["detail_distinct_selected_ids"] = int(
                distinct_selected_ids
            )
        if reconciled_rows is not None:
            metrics_patch["detail_reconciled_rows"] = int(reconciled_rows)
        if duplicate_rows is not None:
            metrics_patch["detail_duplicate_rows"] = int(duplicate_rows)
        self.crawl_job_repository.merge_metrics(
            db,
            crawl_job_id=detail_crawl_job_id,
            metrics_patch=metrics_patch,
            auto_commit=False,
        )

    @staticmethod
    def _distinct_source_job_ids(payloads: list[dict[str, Any]]) -> set[str]:
        return set(CrawlJobRuntime._ordered_distinct_source_job_ids(payloads))

    @staticmethod
    def _ordered_distinct_source_job_ids(
        payloads: list[dict[str, Any]],
    ) -> list[str]:
        return CrawlJobRuntime._ordered_distinct_values(
            payload.get("source_job_id") for payload in payloads
        )

    @staticmethod
    def _ordered_distinct_values(
        values,
        *,
        max_length: int | None = None,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if max_length is not None:
                normalized = normalized[:max_length]
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    @staticmethod
    def _listing_observation_payload(
        *,
        source_job_id: str,
        classification: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        listing_payload = payload.get("listing_payload")
        identity = resolve_offertoday_detail_identity(
            source_job_id=source_job_id,
            listing_payload=(
                dict(listing_payload)
                if isinstance(listing_payload, Mapping)
                else {}
            ),
        )
        return {
            "source_job_id": source_job_id,
            "job_id": identity.job_id,
            "encrypted_job_id": identity.encrypted_job_id,
            "encrypted_job_id_source": identity.encrypted_job_id_source,
            "classification": classification,
            "search_family": CrawlJobRuntime._optional_str(
                payload.get("search_family")
            ),
            "category_id": CrawlJobRuntime._optional_str(
                payload.get("category_id")
                or payload.get("source_classification_id")
            ),
            "category_name": CrawlJobRuntime._optional_str(
                payload.get("category_name")
                or payload.get("source_classification_name")
            ),
            "keyword": CrawlJobRuntime._optional_str(payload.get("keyword")),
            "page": CrawlJobRuntime._optional_int(
                payload.get("page")
                if payload.get("page") is not None
                else payload.get("listing_page")
            ),
        }

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
