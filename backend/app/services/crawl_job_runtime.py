from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.crawl_phases import DEFAULT_DETAIL_RETRY_STATUSES
from app.database import SessionLocal
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.crawl_job_repository import CrawlJobRepository, _UNSET as CRAWL_JOB_REPOSITORY_UNSET
from app.repositories.job_repository import JobRepository
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
    targets: list[dict[str, Any]]


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
                first_payload_by_source_job_id = {
                    source_job_id: next(
                        payload
                        for payload in batch_payloads
                        if str(payload.get("source_job_id") or "").strip()
                        == source_job_id
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
                                classification=classification_by_source_job_id[
                                    source_job_id
                                ],
                                payload=first_payload_by_source_job_id[source_job_id],
                            )
                            for source_job_id in ordered_job_ids
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
            selected_rows = (
                self.crawl_job_listing_repository.list_detail_candidates(
                    db,
                    source_site=normalized_source,
                    source_listing_crawl_job_id=source_listing_crawl_job_id,
                    category_ids=(
                        []
                        if source_job_ids_present
                        else payload.get("category_ids") or []
                    ),
                    statuses=payload.get("detail_statuses"),
                    source_job_ids=source_job_ids,
                    limit=detail_limit,
                )
                if source_job_ids is None or source_job_ids
                else []
            )
            skipped_existing_rows = 0
            existing_jobs_by_source_id = {}
            if payload.get("skip_existing"):
                existing_jobs_by_source_id = self.job_repository.list_existing_jobs_by_source_ids(
                    db,
                    source_site=normalized_source,
                    source_job_ids=[
                        str(getattr(row, "source_job_id", "") or "").strip()
                        for row in selected_rows
                    ],
                )

            targets: list[dict[str, Any]] = []
            for row in selected_rows:
                source_job_id = str(getattr(row, "source_job_id", "") or "").strip()
                existing_job = existing_jobs_by_source_id.get(source_job_id)
                if existing_job is not None:
                    self.crawl_job_listing_repository.mark_detail_completed(
                        db,
                        listing_id=row.id,
                        detail_crawl_job_id=detail_crawl_job_id,
                        detail_payload=dict(getattr(existing_job, "raw_data", None) or {}),
                        published_job_id=getattr(existing_job, "id", None),
                        auto_commit=False,
                    )
                    skipped_existing_rows += 1
                    continue

                targets.append(
                    {
                        "listing_id": row.id,
                        "crawl_job_id": row.crawl_job_id,
                        "source_site": row.source_site,
                        "source_job_id": source_job_id,
                        "source_url": row.source_url,
                        "source_classification_id": row.source_classification_id,
                        "source_classification_name": row.source_classification_name,
                        "listing_payload": dict(getattr(row, "listing_payload", None) or {}),
                        "detail_payload": dict(getattr(row, "detail_payload", None) or {}),
                    }
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
                skipped_existing_rows=skipped_existing_rows,
                target_rows=len(targets),
            )
            db.commit()
            return DetailTargetLoadResult(
                target_rows=len(targets),
                selected_rows=len(selected_rows),
                skipped_existing_rows=skipped_existing_rows,
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

    def mark_detail_running(self, *, listing_id, detail_crawl_job_id) -> None:
        db = self.session_factory()
        try:
            listing = self.crawl_job_listing_repository.mark_detail_running(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                auto_commit=False,
            )
            self._sync_detail_transition_metrics(
                db,
                listing=listing,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
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
            listing = self.crawl_job_listing_repository.mark_detail_completed(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                detail_payload=detail_payload,
                published_job_id=published_job_id,
                auto_commit=False,
            )
            self._sync_detail_transition_metrics(
                db,
                listing=listing,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
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
            listing = self.crawl_job_listing_repository.mark_detail_failed(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                error_message=error_message,
                auto_commit=False,
            )
            self._sync_detail_transition_metrics(
                db,
                listing=listing,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
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
            listing = self.crawl_job_listing_repository.mark_detail_manual_action_required(
                db,
                listing_id=listing_id,
                detail_crawl_job_id=detail_crawl_job_id,
                error_message=error_message,
                auto_commit=False,
            )
            self._sync_detail_transition_metrics(
                db,
                listing=listing,
                detail_crawl_job_id=detail_crawl_job_id,
            )
            db.commit()
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
        self._sync_listing_metrics(
            db,
            crawl_job_id=listing.crawl_job_id,
            source_site=listing.source_site,
            skipped_existing_delta=0,
        )
        self._sync_detail_run_metrics(
            db,
            detail_crawl_job_id=detail_crawl_job_id,
            source_site=listing.source_site,
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
        }
        if selected_rows is not None:
            metrics_patch["detail_selected_rows"] = int(selected_rows)
        if skipped_existing_rows is not None:
            metrics_patch["detail_skipped_existing_rows"] = int(skipped_existing_rows)
        if target_rows is not None:
            metrics_patch["detail_target_rows"] = int(target_rows)
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
        return {
            "source_job_id": source_job_id,
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
