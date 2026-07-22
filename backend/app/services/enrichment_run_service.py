import uuid
import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, TypedDict

from sqlalchemy import and_, case, func, text
from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy import CanonicalTaxonomyPreflight
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
)
from app.messaging.topics import STREAM_JOB_LIFECYCLE
from app.models.crawl_job import CrawlJob
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.source_job_attributes import (
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.models.skill_governance import (
    GovernedJobSkillMention,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
)
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.utils.time import utc_now
from app.workers.event_types import INGEST_ITEM_SETTLED_EVENT_TYPE

ACTIVE_RUN_STATUSES = ("pending", "running", "stopping")
TERMINAL_RUN_STATUSES = (
    "completed",
    "completed_with_failures",
    "completed_with_exclusions",
    "failed",
    "cancelled",
)
RESERVED_RUN_STATUSES = ("waiting", *ACTIVE_RUN_STATUSES)
ACTIVE_SLOT_LOCK_KEY = "job_scraper:enrichment_run:active_slot"


@dataclass(frozen=True)
class CrawlAutoRunAppendResult:
    run: EnrichmentRun
    action: str
    skipped_reason: str | None = None

    @property
    def id(self):
        return self.run.id

    def __getattr__(self, name):
        return getattr(self.run, name)


@dataclass(frozen=True)
class PendingJobFilters:
    source_sites: tuple[str, ...] = ()
    source_classification_ids: tuple[str, ...] = ()
    source_subclassification_ids: tuple[str, ...] = ()
    source_classification_names: tuple[str, ...] = ()
    source_subclassification_names: tuple[str, ...] = ()
    posted_date_from: date | None = None
    posted_date_to: date | None = None

    @property
    def has_constraints(self) -> bool:
        return bool(
            self.source_sites
            or self.source_classification_ids
            or self.source_subclassification_ids
            or self.source_classification_names
            or self.source_subclassification_names
            or self.posted_date_from
            or self.posted_date_to
        )


class _ExcludedTaxonomyGroup(TypedDict):
    source_classification_id: str | None
    source_classification_name: str | None
    count: int
    reason: str
    job_ids: list[str]


@dataclass(frozen=True)
class PendingSelectionReport:
    """Read-only, preflight-backed snapshot of one pending selection."""

    matching_pending_count: int
    selected_job_ids: tuple[str, ...]
    supported_job_ids: tuple[str, ...]
    excluded_reasons_by_job_id: dict[str, str]
    excluded_items: tuple[_ExcludedTaxonomyGroup, ...]

    @property
    def selected_item_count(self) -> int:
        return len(self.selected_job_ids)

    @property
    def effective_item_count(self) -> int:
        return len(self.supported_job_ids)

    @property
    def excluded_item_count(self) -> int:
        return len(self.excluded_reasons_by_job_id)

    def to_preview_payload(self) -> dict[str, object]:
        return {
            "matching_pending_count": self.matching_pending_count,
            "selected_item_count": self.selected_item_count,
            "effective_item_count": self.effective_item_count,
            "excluded_item_count": self.excluded_item_count,
            "excluded_items": [dict(item) for item in self.excluded_items],
        }


class ActiveEnrichmentRunError(RuntimeError):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"Enrichment run {run_id} already owns the active slot")


class EnrichmentRunService:
    """Persist enrichment runs and their items."""

    def __init__(
        self,
        db: Session,
        *,
        taxonomy_preflight: CanonicalTaxonomyPreflight | None = None,
    ):
        self.db = db
        self.crawl_job_repository = CrawlJobRepository()
        self.event_outbox_repository = EventOutboxRepository()
        self.taxonomy_preflight = taxonomy_preflight or CanonicalTaxonomyPreflight(db)

    def _query_ai_actionable_jobs(self, *entities):
        return self.db.query(*entities).filter(
            Job.is_deleted.is_(False),
            Job.source_attribute_projection.has(),
        )

    def _acquire_active_slot_lock(self) -> None:
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": ACTIVE_SLOT_LOCK_KEY},
            )

    def get_active_run(self) -> Optional[EnrichmentRun]:
        return (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(EnrichmentRun.created_at.asc(), EnrichmentRun.id.asc())
            .first()
        )

    def _require_active_slot(self) -> None:
        self._acquire_active_slot_lock()
        active_run = self.get_active_run()
        if active_run is not None:
            raise ActiveEnrichmentRunError(active_run.id)

    def _reserved_job_exists(self):
        return (
            self.db.query(EnrichmentRunItem.id)
            .join(EnrichmentRun, EnrichmentRun.id == EnrichmentRunItem.run_id)
            .filter(
                EnrichmentRunItem.job_id == Job.id,
                EnrichmentRun.status.in_(RESERVED_RUN_STATUSES),
                EnrichmentRunItem.status.in_(("pending", "running")),
            )
            .exists()
        )

    def _query_pending_candidates(
        self, *entities, filters: PendingJobFilters | None = None
    ):
        normalized = filters or PendingJobFilters()
        query = self._query_ai_actionable_jobs(*entities).filter(
            Job.ai_enriched_at.is_(None),
            ~self._reserved_job_exists(),
        )
        if normalized.source_sites:
            query = query.filter(
                func.lower(Job.source_site).in_(normalized.source_sites)
            )
        if normalized.source_classification_ids:
            query = query.filter(
                Job.source_classification_paths.any(
                    JobSourceClassificationPath.nodes.any(
                        and_(
                            JobSourceClassificationPathNode.source_position == 0,
                            JobSourceClassificationPathNode.source_classification_id.in_(
                                normalized.source_classification_ids
                            ),
                        )
                    )
                )
            )
        if normalized.source_subclassification_ids:
            query = query.filter(
                Job.source_classification_paths.any(
                    JobSourceClassificationPath.nodes.any(
                        and_(
                            JobSourceClassificationPathNode.source_position > 0,
                            JobSourceClassificationPathNode.source_classification_id.in_(
                                normalized.source_subclassification_ids
                            ),
                        )
                    )
                )
            )
        if normalized.source_classification_names:
            query = query.filter(
                func.lower(Job.source_classification_name).in_(
                    normalized.source_classification_names
                )
            )
        if normalized.source_subclassification_names:
            query = query.filter(
                func.lower(Job.source_subclassification_name).in_(
                    normalized.source_subclassification_names
                )
            )
        if normalized.posted_date_from is not None:
            query = query.filter(
                func.date(Job.posted_date) >= normalized.posted_date_from
            )
        if normalized.posted_date_to is not None:
            query = query.filter(
                func.date(Job.posted_date) <= normalized.posted_date_to
            )
        return query

    def preview_pending_jobs(
        self, *, filters: PendingJobFilters, limit: int
    ) -> dict[str, object]:
        return self.inspect_pending_selection(filters=filters, limit=limit).to_preview_payload()

    def inspect_pending_selection(
        self, *, filters: PendingJobFilters, limit: int
    ) -> PendingSelectionReport:
        """Resolve one oldest-first pending slice and its taxonomy preflight."""
        matching_count = int(
            self._query_pending_candidates(func.count(Job.id), filters=filters).scalar()
            or 0
        )
        selected_jobs = self._select_pending_jobs(filters=filters, limit=limit)
        supported_jobs, excluded_reasons, excluded_items = self._preflight_jobs(
            selected_jobs
        )
        return PendingSelectionReport(
            matching_pending_count=matching_count,
            selected_job_ids=tuple(str(job.id) for job in selected_jobs),
            supported_job_ids=tuple(str(job.id) for job in supported_jobs),
            excluded_reasons_by_job_id=dict(excluded_reasons),
            excluded_items=tuple(excluded_items),
        )

    def _select_pending_jobs(
        self,
        *,
        filters: PendingJobFilters | None,
        limit: Optional[int],
    ) -> list[Job]:
        query = self._query_pending_candidates(Job, filters=filters).order_by(
            Job.created_at.asc(), Job.id.asc()
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def _preflight_jobs(
        self,
        jobs: list[Job],
    ) -> tuple[list[Job], dict[str, str], list[_ExcludedTaxonomyGroup]]:
        supported_jobs: list[Job] = []
        excluded_reasons: dict[str, str] = {}
        grouped: dict[
            tuple[str | None, str | None, str],
            _ExcludedTaxonomyGroup,
        ] = {}

        for job in jobs:
            handling = self.taxonomy_preflight.inspect(job)
            if handling.status == "supported":
                supported_jobs.append(job)
                continue

            source_id = str(job.source_classification_id or "").strip() or None
            source_name = str(job.source_classification_name or "").strip() or None
            reason = handling.reason or "canonical_taxonomy_preflight_blocked"
            excluded_reasons[str(job.id)] = reason
            key = (
                source_id,
                source_name,
                reason,
            )
            group = grouped.setdefault(
                key,
                {
                    # These legacy scalars are display-only compatibility evidence.
                    # Canonical eligibility above comes exclusively from preserved
                    # Source Classification Paths and the active mapping release.
                    "source_classification_id": source_id,
                    "source_classification_name": source_name,
                    "count": 0,
                    "reason": reason,
                    "job_ids": [],
                },
            )
            group["count"] = int(group["count"]) + 1
            group["job_ids"].append(str(job.id))

        return supported_jobs, excluded_reasons, list(grouped.values())

    def get_pending_filter_options(self) -> list[dict[str, object]]:
        candidate_ids = self._query_pending_candidates(Job.id).subquery()
        rows = (
            self.db.query(
                JobSourceClassificationPath.id,
                JobSourceClassificationPath.source_site,
                JobSourceClassificationPathNode.source_position,
                JobSourceClassificationPathNode.source_classification_id,
                JobSourceClassificationPathNode.label,
            )
            .join(candidate_ids, candidate_ids.c.id == JobSourceClassificationPath.job_id)
            .join(
                JobSourceClassificationPathNode,
                JobSourceClassificationPathNode.path_id
                == JobSourceClassificationPath.id,
            )
            .order_by(
                JobSourceClassificationPath.source_site.asc(),
                JobSourceClassificationPath.id.asc(),
                JobSourceClassificationPathNode.source_position.asc(),
            )
            .all()
        )
        paths: dict[str, dict[str, object]] = {}
        for path_id, source_site, source_position, classification_id, label in rows:
            path = paths.setdefault(
                str(path_id),
                {"source_site": source_site, "nodes": []},
            )
            path["nodes"].append(
                {
                    "source_position": int(source_position),
                    "source_classification_id": classification_id,
                    "label": label,
                }
            )
        return list(paths.values())

    def get_job_queue_counts(self) -> dict[str, int]:
        total_jobs, enriched_jobs, eligible_enriched_jobs, eligible_unenriched_jobs = (
            self.db.query(
                func.count(Job.id),
                func.count(Job.ai_enriched_at),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Job.ai_enriched_at.isnot(None),
                                    Job.source_attribute_projection.has(),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Job.ai_enriched_at.is_(None),
                                    Job.source_attribute_projection.has(),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .filter(Job.is_deleted.is_(False))
            .one()
        )
        pending_jobs = int(
            self._query_pending_candidates(func.count(Job.id)).scalar() or 0
        )
        ai_eligible_jobs = int(
            (eligible_enriched_jobs or 0) + (eligible_unenriched_jobs or 0)
        )
        total_jobs = int(total_jobs or 0)
        return {
            "total_jobs": total_jobs,
            "enriched_jobs": int(enriched_jobs or 0),
            "eligible_enriched_jobs": int(eligible_enriched_jobs or 0),
            "ai_eligible_jobs": ai_eligible_jobs,
            "ineligible_jobs": max(total_jobs - ai_eligible_jobs, 0),
            "pending_jobs": int(pending_jobs or 0),
        }

    def create_post_scrape_run(self, job_ids: List[str]) -> EnrichmentRun:
        """Persist a post-scrape run for internal `jobs.id` UUID values."""
        self._acquire_active_slot_lock()
        initial_status = "waiting" if self.get_active_run() is not None else "pending"
        return self._create_run(
            source_type="post_scrape",
            job_ids=job_ids,
            initial_status=initial_status,
        )

    def _create_run(
        self,
        source_type: str,
        job_ids: List[str],
        *,
        trigger_crawl_job_id: str | uuid.UUID | None = None,
        initial_status: str = "pending",
        excluded_reasons_by_job_id: dict[str, str] | None = None,
    ) -> EnrichmentRun:
        """Persist a run and its pending items for internal `jobs.id` UUID values."""
        normalized_job_ids = [str(job_id) for job_id in job_ids]
        item_count = len(normalized_job_ids)
        excluded_reasons = excluded_reasons_by_job_id or {}
        excluded_count = sum(
            1 for job_id in normalized_job_ids if job_id in excluded_reasons
        )
        pending_count = item_count - excluded_count
        effective_status = initial_status
        if (
            excluded_count
            and pending_count == 0
            and initial_status in {"pending", "waiting"}
        ):
            effective_status = "completed_with_exclusions"
        completed_at = (
            utc_now() if effective_status == "completed_with_exclusions" else None
        )
        run = EnrichmentRun(
            source_type=source_type,
            trigger_crawl_job_id=uuid.UUID(str(trigger_crawl_job_id))
            if trigger_crawl_job_id
            else None,
            status=effective_status,
            job_ids=normalized_job_ids,
            total_items=item_count,
            pending_items=pending_count,
            completed_items=0,
            failed_items=0,
            cancelled_items=0,
            excluded_items=excluded_count,
            completed_at=completed_at,
        )
        self.db.add(run)
        self.db.flush()

        for position, job_id in enumerate(normalized_job_ids):
            self.db.add(
                EnrichmentRunItem(
                    run_id=run.id,
                    job_id=uuid.UUID(job_id),
                    position=position,
                    status=("excluded" if job_id in excluded_reasons else "pending"),
                    error_message=excluded_reasons.get(job_id),
                )
            )

        self.db.flush()
        return run

    def create_post_scrape_run_for_batch(
        self, job_ids: List[str]
    ) -> Optional[EnrichmentRun]:
        """Create a post-scrape run only when the scrape batch persisted rows."""
        if not job_ids:
            return None

        return self.create_post_scrape_run(job_ids=job_ids)

    def create_manual_job_run(self, job_id: str) -> EnrichmentRun:
        """Create the internal run used by the manual-job creation workflow."""
        self._require_active_slot()
        return self._create_run(source_type="manual_job_create", job_ids=[job_id])

    def create_manual_query_run(
        self,
        *,
        review_candidate_names: Optional[List[str]] = None,
        polluted_skill_names: Optional[List[str]] = None,
        source_subclassification_names: Optional[List[str]] = None,
        scope: str = "all",
    ) -> Optional[EnrichmentRun]:
        """Create a manual run from governance-oriented selectors."""
        self._require_active_slot()
        job_ids = self._select_manual_query_job_ids(
            review_candidate_names=review_candidate_names,
            polluted_skill_names=polluted_skill_names,
            source_subclassification_names=source_subclassification_names,
            scope=scope,
        )
        if not job_ids:
            return None
        return self._create_run(source_type="manual_query", job_ids=job_ids)

    def create_manual_pending_run(
        self,
        limit: Optional[int] = None,
        *,
        filters: PendingJobFilters | None = None,
    ) -> Optional[EnrichmentRun]:
        """Create a manual run from filtered pending unenriched jobs."""
        self._require_active_slot()
        selected_jobs = self._select_pending_jobs(filters=filters, limit=limit)
        if not selected_jobs:
            return None
        _, excluded_reasons_by_job_id, _ = self._preflight_jobs(selected_jobs)
        return self._create_run(
            source_type="manual_pending",
            job_ids=[str(job.id) for job in selected_jobs],
            excluded_reasons_by_job_id=excluded_reasons_by_job_id,
        )

    def get_crawl_auto_run(self, crawl_job_id: str) -> Optional[EnrichmentRun]:
        crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        return (
            self.db.query(EnrichmentRun)
            .filter(
                EnrichmentRun.source_type == "crawl_auto",
                EnrichmentRun.trigger_crawl_job_id == crawl_job_uuid,
            )
            .order_by(
                EnrichmentRun.created_at.desc(),
                EnrichmentRun.id.desc(),
            )
            .first()
        )

    def append_job_to_crawl_auto_run(
        self, *, crawl_job_id: str, job_id: str
    ) -> CrawlAutoRunAppendResult:
        crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        job_uuid = uuid.UUID(str(job_id))
        run = self.get_crawl_auto_run(str(crawl_job_uuid))
        if run is None:
            run = self._create_run(
                source_type="crawl_auto",
                job_ids=[],
                trigger_crawl_job_id=crawl_job_uuid,
                initial_status="waiting",
            )
            run.total_items = 0
            run.pending_items = 0
            run.completed_items = 0
            run.failed_items = 0
            run.job_ids = []
            run.excluded_items = 0
            self.db.flush()

        existing_item = (
            self.db.query(EnrichmentRunItem)
            .filter(
                EnrichmentRunItem.run_id == run.id,
                EnrichmentRunItem.job_id == job_uuid,
            )
            .first()
        )
        if existing_item is not None:
            return CrawlAutoRunAppendResult(run=run, action="duplicate")

        if run.status not in {"waiting", "pending"}:
            return CrawlAutoRunAppendResult(
                run=run,
                action="skipped_terminal",
                skipped_reason=f"run_status={run.status}",
            )

        next_position = len(list(run.job_ids or []))
        run.job_ids = list(run.job_ids or []) + [str(job_uuid)]
        run.total_items = int(run.total_items or 0) + 1
        run.pending_items = int(run.pending_items or 0) + 1
        self.db.add(
            EnrichmentRunItem(
                run_id=run.id,
                job_id=job_uuid,
                position=next_position,
                status="pending",
            )
        )
        self.db.flush()
        return CrawlAutoRunAppendResult(run=run, action="added")

    def request_run_execution(
        self, run_id: str, *, source_service: str = "ai-api"
    ) -> bool:
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one_or_none()
        )
        if run is None or run.status != "pending":
            return False

        existing_request = (
            self.db.query(EventOutbox.id)
            .filter(
                EventOutbox.aggregate_type == "enrichment_run",
                EventOutbox.aggregate_id == run.id,
                EventOutbox.event_type == "enrichment.run.requested",
            )
            .first()
        )
        if existing_request is not None:
            return False

        self.event_outbox_repository.enqueue(
            self.db,
            topic=STREAM_JOB_LIFECYCLE,
            aggregate_type="enrichment_run",
            aggregate_id=run.id,
            event_type="enrichment.run.requested",
            payload=self._build_run_requested_payload(run),
            source_service=source_service,
            auto_commit=False,
        )
        self.db.flush()
        return True

    def request_ready_pending_runs(
        self, *, source_service: str = "enrichment-worker"
    ) -> int:
        self.promote_next_ready_waiting_run(source_service=source_service)
        pending_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status == "pending")
            .order_by(EnrichmentRun.created_at.asc(), EnrichmentRun.id.asc())
            .all()
        )
        requested_count = 0
        for run in pending_runs:
            gate = self.describe_pending_gate(run)
            if gate is None or gate.get("reason") != "queued_for_execution":
                continue
            if self.request_run_execution(run.id, source_service=source_service):
                requested_count += 1
        return requested_count

    def promote_next_ready_waiting_run(
        self,
        *,
        source_service: str = "enrichment-worker",
    ) -> Optional[EnrichmentRun]:
        """Promote the oldest ready automatic run when the active slot is free."""
        self._acquire_active_slot_lock()
        if self.get_active_run() is not None:
            return None

        waiting_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status == "waiting")
            .order_by(EnrichmentRun.created_at.asc(), EnrichmentRun.id.asc())
            .all()
        )
        for run in waiting_runs:
            gate = self.describe_pending_gate(run)
            if gate is None or gate.get("reason") != "queued_for_execution":
                continue
            run.status = "pending"
            self.db.flush()
            self.request_run_execution(run.id, source_service=source_service)
            return run
        return None

    def request_crawl_auto_run_if_ready(self, crawl_job_id: str) -> bool:
        crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        crawl_job = (
            self.db.query(CrawlJob).filter(CrawlJob.id == crawl_job_uuid).first()
        )
        run = self.get_crawl_auto_run(str(crawl_job_uuid))
        if crawl_job is None or run is None:
            return False
        gate = self.describe_pending_gate(run, crawl_job=crawl_job)
        if gate is None:
            return False
        if gate["reason"] != "queued_for_execution":
            return False
        if run.status == "waiting":
            promoted = self.promote_next_ready_waiting_run()
            return promoted is not None and promoted.id == run.id
        return self.request_run_execution(run.id, source_service="enrichment-worker")

    def describe_pending_gate(
        self,
        run: EnrichmentRun,
        *,
        crawl_job: CrawlJob | None = None,
    ) -> Dict[str, object] | None:
        if (
            str(run.status or "").lower() not in {"waiting", "pending"}
            or run.started_at is not None
        ):
            return None

        if not run.total_items:
            return {
                "reason": "queued_for_execution",
            }

        if run.source_type != "crawl_auto" or run.trigger_crawl_job_id is None:
            return {
                "reason": "queued_for_execution",
            }

        if (
            not AIRuntimeSettingsService(self.db)
            .get_profile_runtime_metadata("jobs")
            .is_ready
        ):
            return {
                "reason": "waiting_for_ai_runtime",
            }

        resolved_crawl_job = crawl_job
        if resolved_crawl_job is None:
            resolved_crawl_job = (
                self.db.query(CrawlJob)
                .filter(CrawlJob.id == run.trigger_crawl_job_id)
                .first()
            )

        if resolved_crawl_job is None:
            return {
                "reason": "waiting_for_crawl_completion",
                "crawl_job_status": "missing",
            }

        if resolved_crawl_job.status not in {"completed", "failed"}:
            return {
                "reason": "waiting_for_crawl_completion",
                "crawl_job_status": str(resolved_crawl_job.status or "unknown"),
            }

        metrics = dict(resolved_crawl_job.metrics or {})
        items_emitted = int(metrics.get("items_emitted") or 0)
        ingest_items_seen = int(metrics.get("ingest_items_seen") or 0)
        ingest_items_failed = int(metrics.get("ingest_items_failed") or 0)
        ingest_dead_lettered = int(metrics.get("ingest_dead_lettered") or 0)
        effective_ingest_items_seen = max(ingest_items_seen, int(run.total_items or 0))
        ingest_items_settled = effective_ingest_items_seen + max(
            ingest_items_failed, ingest_dead_lettered
        )
        settled_event_count = self.crawl_job_repository.count_events(
            self.db,
            resolved_crawl_job.id,
            event_types={INGEST_ITEM_SETTLED_EVENT_TYPE},
        )
        if settled_event_count > 0:
            ingest_items_settled = max(ingest_items_settled, int(settled_event_count))
        if items_emitted > 0 and ingest_items_settled < items_emitted:
            return {
                "reason": "waiting_for_ingest_settle",
                "emitted_items": items_emitted,
                "settled_items": ingest_items_settled,
                "crawl_job_status": str(resolved_crawl_job.status or "unknown"),
            }

        return {
            "reason": "queued_for_execution",
        }

    def _select_manual_query_job_ids(
        self,
        *,
        review_candidate_names: Optional[List[str]],
        polluted_skill_names: Optional[List[str]],
        source_subclassification_names: Optional[List[str]],
        scope: str,
    ) -> list[str]:
        # ``polluted_skill_names`` remains an input-only compatibility alias.
        # Both selectors now resolve against governed pending Candidates.
        normalized_candidate_names = self._normalize_selector_values(
            [*(review_candidate_names or []), *(polluted_skill_names or [])],
            normalizer=normalize_exact_skill_key,
        )
        if not normalized_candidate_names:
            raise ValueError("At least one query selector is required")

        if scope not in {"all", "enriched_only"}:
            raise ValueError(f"Unsupported query scope: {scope}")

        selected_job_ids: set[uuid.UUID] = set()
        review_candidate_ids = self._find_review_candidate_ids(
            normalized_candidate_names
        )
        if review_candidate_ids:
            selected_job_ids.update(
                job_id
                for (job_id,) in (
                    self.db.query(GovernedJobSkillMention.job_id)
                    .filter(
                        GovernedJobSkillMention.candidate_id.in_(review_candidate_ids),
                        GovernedJobSkillMention.resolution == "review_candidate",
                        GovernedJobSkillMention.status == "active",
                    )
                    .all()
                )
            )

        if not selected_job_ids:
            return []

        query = self.db.query(Job.id).filter(
            Job.id.in_(selected_job_ids),
            Job.is_deleted.is_(False),
            Job.source_classification_id.isnot(None),
            Job.source_classification_id != "",
        )
        if scope == "enriched_only":
            query = query.filter(Job.ai_enriched_at.isnot(None))

        normalized_subclassification_names = {
            str(value).strip().lower()
            for value in (source_subclassification_names or [])
            if str(value).strip()
        }
        if normalized_subclassification_names:
            query = query.filter(
                func.lower(Job.source_subclassification_name).in_(
                    normalized_subclassification_names
                )
            )

        return [
            str(row.id)
            for row in query.order_by(Job.created_at.asc(), Job.id.asc()).all()
        ]

    def _normalize_selector_values(
        self,
        values: Optional[Iterable[str]],
        *,
        normalizer,
    ) -> set[str]:
        normalized = set()
        for value in values or []:
            normalized_value = normalizer(str(value or ""))
            if normalized_value:
                normalized.add(normalized_value)
        return normalized

    def _find_review_candidate_ids(self, normalized_names: set[str]) -> set[uuid.UUID]:
        if not normalized_names:
            return set()
        active = self.db.get(SkillTaxonomyActiveRevision, "skill-taxonomy")
        if active is None:
            return set()

        return {
            candidate_id
            for (candidate_id,) in (
                self.db.query(SkillCandidate.id)
                .filter(
                    SkillCandidate.taxonomy_revision_id == active.revision_id,
                    SkillCandidate.status == "pending",
                    SkillCandidate.normalized_key.in_(normalized_names),
                )
                .all()
            )
        }

    def get_run(self, run_id: str) -> Optional[EnrichmentRun]:
        """Fetch a persisted run by ID."""
        return self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).first()

    def claim_run(self, run_id: str) -> Optional[EnrichmentRun]:
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one_or_none()
        )
        if run is None or run.status != "pending":
            return None

        now = utc_now()
        run.status = "running"
        run.started_at = run.started_at or now
        run.completed_at = None
        run.error_message = None
        run.current_job_title = None
        self.db.commit()
        self.db.refresh(run)
        return run

    def list_runs(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[EnrichmentRun]:
        """List persisted runs with optional filters."""
        query = self.db.query(EnrichmentRun)
        if status:
            query = query.filter(EnrichmentRun.status == status)
        if source_type:
            query = query.filter(EnrichmentRun.source_type == source_type)
        query = query.order_by(
            EnrichmentRun.created_at.desc(),
            EnrichmentRun.id.desc(),
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def list_runs_for_monitor(self) -> List[EnrichmentRun]:
        """Return active + latest terminal, or the two latest terminal runs."""
        active_run = self.get_active_run()
        terminal_limit = 1 if active_run is not None else 2
        terminal_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status.in_(TERMINAL_RUN_STATUSES))
            .order_by(
                EnrichmentRun.completed_at.desc(),
                EnrichmentRun.created_at.desc(),
                EnrichmentRun.id.desc(),
            )
            .limit(terminal_limit)
            .all()
        )
        return ([active_run] if active_run is not None else []) + terminal_runs

    def list_run_items(
        self,
        run_id: str,
        status: Optional[str] = None,
    ) -> List[EnrichmentRunItem]:
        """List items for a run, optionally filtered by item status."""
        query = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.run_id == run_id)
            .order_by(EnrichmentRunItem.position.asc())
        )
        if status:
            query = query.filter(EnrichmentRunItem.status == status)
        return query.all()

    def list_run_items_or_none(
        self,
        run_id: str,
        status: Optional[str] = None,
    ) -> Optional[List[EnrichmentRunItem]]:
        """List items for an existing run in one query, or return None when the run is missing."""
        join_conditions = [EnrichmentRunItem.run_id == EnrichmentRun.id]
        if status:
            join_conditions.append(EnrichmentRunItem.status == status)

        rows = (
            self.db.query(
                EnrichmentRun.id.label("run_id"),
                EnrichmentRunItem,
            )
            .select_from(EnrichmentRun)
            .outerjoin(EnrichmentRunItem, and_(*join_conditions))
            .filter(EnrichmentRun.id == run_id)
            .order_by(
                EnrichmentRunItem.position.asc(),
                EnrichmentRunItem.id.asc(),
            )
            .all()
        )
        if not rows:
            return None
        return [item for _, item in rows if item is not None]

    def mark_run_failed(
        self, run_id: str, error_message: str
    ) -> Optional[EnrichmentRun]:
        """Persist a terminal failure state for a run when orchestration aborts."""
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status == "stopping":
            return self._finalize_stopping_run(run, error_message=error_message)
        if run.status in TERMINAL_RUN_STATUSES:
            return run

        items = self.list_run_items(run_id)
        completed_items = 0
        failed_items = 0
        excluded_items = 0
        timestamp = utc_now()
        latest_failure_timestamp = timestamp
        running_items = [item for item in items if item.status == "running"]
        pending_items = [item for item in items if item.status == "pending"]

        for item in items:
            if item.status == "completed":
                completed_items += 1
                continue

            if item.status == "failed":
                # Preserve item-level diagnostics from earlier failures.
                if item.started_at is None:
                    item.started_at = timestamp
                if item.completed_at is None:
                    item.completed_at = timestamp
                failed_items += 1
                continue

            if item.status == "excluded":
                excluded_items += 1
        for item in pending_items:
            item.status = "failed"
            item.error_message = error_message
            if item.started_at is None:
                item.started_at = timestamp
            item.completed_at = timestamp
            failed_items += 1

        for offset, item in enumerate(running_items, start=1):
            failure_timestamp = timestamp + timedelta(microseconds=offset)
            item.status = "failed"
            item.error_message = error_message
            if item.started_at is None:
                item.started_at = timestamp
            item.completed_at = failure_timestamp
            failed_items += 1
            latest_failure_timestamp = failure_timestamp

        if failed_items > 0:
            run.status = "failed" if completed_items == 0 else "completed_with_failures"
        elif excluded_items > 0:
            run.status = "completed_with_exclusions"
        else:
            run.status = "failed"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        run.cancelled_items = 0
        run.excluded_items = excluded_items
        if run.started_at is None:
            run.started_at = timestamp
        run.completed_at = latest_failure_timestamp
        run.current_job_title = None
        run.error_message = error_message
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.flush()
        self.promote_next_ready_waiting_run()
        self.db.flush()
        return run

    def cancel_run(self, run_id: str, error_message: str) -> Optional[EnrichmentRun]:
        """Cancel an unclaimed run without converting its items into failed jobs."""
        run = self.get_run(run_id)
        if run is None:
            return None

        items = self.list_run_items(run_id)
        timestamp = utc_now()
        completed_items = 0
        failed_items = 0
        cancelled_items = 0
        excluded_items = 0

        for item in items:
            if item.status == "completed":
                completed_items += 1
                continue
            if item.status == "failed":
                failed_items += 1
                continue
            if item.status == "excluded":
                excluded_items += 1
                continue

            item.status = "cancelled"
            item.error_message = error_message
            if item.started_at is None:
                item.started_at = timestamp
            item.completed_at = timestamp
            cancelled_items += 1

        run.status = "cancelled"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        run.cancelled_items = cancelled_items
        run.excluded_items = excluded_items
        if run.started_at is None:
            run.started_at = timestamp
        run.completed_at = timestamp
        run.current_job_title = None
        run.error_message = error_message
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.flush()
        self.promote_next_ready_waiting_run()
        self.db.flush()
        return run

    def request_stop(self, run_id: str) -> Optional[EnrichmentRun]:
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one_or_none()
        )
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return run
        if run.status in {"waiting", "pending"}:
            return self.cancel_run(run.id, "Stopped by operator")
        if run.status == "running":
            run.status = "stopping"
            run.stop_requested_at = utc_now()
            run.error_message = (
                "Stop requested by operator; in-flight items are finishing"
            )
            self.db.flush()
        return run

    def _finalize_stopping_run(
        self,
        run: EnrichmentRun,
        *,
        error_message: str = "Stopped by operator",
    ) -> EnrichmentRun:
        items = self.list_run_items(run.id)
        timestamp = utc_now()
        for item in items:
            if item.status != "pending":
                continue
            item.status = "cancelled"
            item.error_message = error_message
            item.started_at = item.started_at or timestamp
            item.completed_at = timestamp

        self.db.flush()
        counts = self._count_items_by_status(run.id)
        run.status = "cancelled"
        run.pending_items = 0
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.cancelled_items = counts["cancelled"]
        run.excluded_items = counts["excluded"]
        run.completed_at = timestamp
        run.current_job_title = None
        run.error_message = error_message
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.flush()
        self.promote_next_ready_waiting_run()
        self.db.flush()
        return run

    def get_overview(self) -> dict:
        """Return AI enrichment overview counters and last completed run."""
        queue_counts = self.get_job_queue_counts()
        running_runs, active_runs = self.db.query(
            func.coalesce(
                func.sum(case((EnrichmentRun.status == "running", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES), 1), else_=0)
                ),
                0,
            ),
        ).one()
        failed_items = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.status == "failed")
            .count()
        )
        failed_jobs = self._count_current_failed_jobs() if failed_items > 0 else 0
        last_completed_run = (
            self.db.query(EnrichmentRun)
            .filter(
                EnrichmentRun.status.in_(
                    [
                        "completed",
                        "completed_with_failures",
                        "completed_with_exclusions",
                    ]
                )
            )
            .order_by(
                EnrichmentRun.completed_at.desc(),
                EnrichmentRun.created_at.desc(),
            )
            .first()
        )

        return {
            "total_jobs": queue_counts["total_jobs"],
            "enriched_jobs": queue_counts["enriched_jobs"],
            "eligible_enriched_jobs": queue_counts["eligible_enriched_jobs"],
            "ai_eligible_jobs": queue_counts["ai_eligible_jobs"],
            "ineligible_jobs": queue_counts["ineligible_jobs"],
            "pending_jobs": queue_counts["pending_jobs"],
            "running_runs": running_runs,
            "active_runs": active_runs,
            "failed_jobs": failed_jobs,
            "failed_items": failed_items,
            "last_completed_run": last_completed_run,
        }

    def _count_current_failed_jobs(self) -> int:
        latest_item_per_job = self.db.query(
            EnrichmentRunItem.job_id.label("job_id"),
            EnrichmentRunItem.status.label("status"),
            func.row_number()
            .over(
                partition_by=EnrichmentRunItem.job_id,
                order_by=(
                    EnrichmentRunItem.created_at.desc(),
                    EnrichmentRunItem.id.desc(),
                ),
            )
            .label("row_number"),
        ).subquery()

        return int(
            self.db.query(func.count())
            .select_from(latest_item_per_job)
            .join(Job, Job.id == latest_item_per_job.c.job_id)
            .filter(
                latest_item_per_job.c.row_number == 1,
                latest_item_per_job.c.status == "failed",
                Job.ai_enriched_at.is_(None),
                Job.is_deleted.is_(False),
            )
            .scalar()
            or 0
        )

    def _compute_in_progress_items(self, run: EnrichmentRun) -> int:
        if run.status not in ACTIVE_RUN_STATUSES:
            return 0
        in_progress = (
            int(run.total_items or 0)
            - int(run.pending_items or 0)
            - int(run.completed_items or 0)
            - int(run.failed_items or 0)
            - int(run.cancelled_items or 0)
            - int(run.excluded_items or 0)
        )
        return max(in_progress, 0)

    def _sync_linked_crawl_job_ai_metrics(self, run: EnrichmentRun) -> None:
        if run.trigger_crawl_job_id is None:
            return

        metrics_patch = {
            "ai_run_id": run.id,
            "ai_total_items": int(run.total_items or 0),
            "ai_completed_items": int(run.completed_items or 0),
            "ai_failed_items": int(run.failed_items or 0),
        }
        self.crawl_job_repository.merge_metrics(
            self.db,
            crawl_job_id=run.trigger_crawl_job_id,
            metrics_patch=metrics_patch,
            auto_commit=False,
        )

    def _serialize_run_progress(self, run_id: str) -> Dict[str, object]:
        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        return {
            "status": run.status,
            "pending_items": run.pending_items,
            "completed_items": run.completed_items,
            "failed_items": run.failed_items,
            "cancelled_items": run.cancelled_items,
            "excluded_items": run.excluded_items,
            "current_job_title": run.current_job_title,
            "in_progress_items": self._compute_in_progress_items(run),
        }

    def _count_items_by_status(self, run_id: str) -> Dict[str, int]:
        counts = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "excluded": 0,
        }
        rows = (
            self.db.query(
                EnrichmentRunItem.status,
                func.count(EnrichmentRunItem.id),
            )
            .filter(EnrichmentRunItem.run_id == run_id)
            .group_by(EnrichmentRunItem.status)
            .all()
        )
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    def _resolve_latest_running_job_title(self, run_id: str) -> Optional[str]:
        latest_running_item = (
            self.db.query(EnrichmentRunItem)
            .filter(
                EnrichmentRunItem.run_id == run_id,
                EnrichmentRunItem.status == "running",
            )
            .order_by(
                EnrichmentRunItem.started_at.desc(),
                EnrichmentRunItem.position.desc(),
            )
            .first()
        )
        if latest_running_item is None:
            return None
        return self._get_job_title(latest_running_item.job_id)

    def _job_id_param(self, job_id: uuid.UUID):
        dialect = self.db.get_bind().dialect.name
        if dialect == "sqlite":
            return job_id.hex
        return job_id

    def _get_job_title(self, job_id: uuid.UUID) -> Optional[str]:
        row = self.db.execute(
            text("SELECT title FROM jobs WHERE id = :job_id"),
            {"job_id": self._job_id_param(job_id)},
        ).first()
        return row[0] if row else None

    def _update_item_started(
        self,
        run_id: str,
        item_id: str,
        job_title: Optional[str],
    ) -> Optional[Dict[str, object]]:
        timestamp = utc_now()
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one()
        )
        item = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.id == item_id)
            .with_for_update()
            .one()
        )
        if run.status != "running" or item.status != "pending":
            self.db.commit()
            return None

        item.status = "running"
        item.started_at = item.started_at or timestamp
        run.current_job_title = job_title
        run.error_message = None
        self.db.flush()
        counts = self._count_items_by_status(run_id)
        run.pending_items = counts["pending"]
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.cancelled_items = counts["cancelled"]
        run.excluded_items = counts["excluded"]
        self.db.commit()
        return self._serialize_run_progress(run_id)

    def _update_item_finished(
        self,
        run_id: str,
        item_id: str,
        result: Dict[str, object],
    ) -> Optional[Dict[str, object]]:
        timestamp = utc_now()
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one()
        )
        item = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.id == item_id)
            .with_for_update()
            .one()
        )
        if run.status not in {"running", "stopping"} or item.status != "running":
            self.db.commit()
            return None

        if result.get("status") == "success":
            item.status = "completed"
            item.error_message = None
            self._enqueue_job_enriched_event(run=run, item=item)
        elif result.get("status") == "excluded":
            item.status = "excluded"
            item.error_message = str(
                result.get("error") or "canonical_taxonomy_preflight_blocked"
            )
        else:
            item.status = "failed"
            item.error_message = str(
                result.get("error") or "missing result for run item"
            )

        item.completed_at = timestamp

        self.db.flush()
        counts = self._count_items_by_status(run_id)
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.pending_items = counts["pending"]
        run.cancelled_items = counts["cancelled"]
        run.excluded_items = counts["excluded"]
        run.current_job_title = self._resolve_latest_running_job_title(run_id)
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.commit()
        return self._serialize_run_progress(run_id)

    def _update_item_excluded(
        self,
        run_id: str,
        item_id: str,
        reason: str,
    ) -> Optional[Dict[str, object]]:
        timestamp = utc_now()
        run = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .with_for_update()
            .one()
        )
        item = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.id == item_id)
            .with_for_update()
            .one()
        )
        if run.status not in {"running", "stopping"} or item.status != "pending":
            self.db.commit()
            return None

        item.status = "excluded"
        item.error_message = reason
        item.completed_at = timestamp
        self.db.flush()
        counts = self._count_items_by_status(run_id)
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.pending_items = counts["pending"]
        run.cancelled_items = counts["cancelled"]
        run.excluded_items = counts["excluded"]
        run.current_job_title = self._resolve_latest_running_job_title(run_id)
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.commit()
        return self._serialize_run_progress(run_id)

    def _resolve_run_concurrency(self) -> int:
        effective_settings = AIRuntimeSettingsService(self.db).get_effective_settings()
        return max(1, int(effective_settings.ai_enrichment_run_concurrency or 1))

    def _build_run_requested_payload(self, run: EnrichmentRun) -> dict[str, object]:
        return {
            "run_id": run.id,
            "source_type": run.source_type,
            "trigger_crawl_job_id": str(run.trigger_crawl_job_id)
            if run.trigger_crawl_job_id
            else None,
            "total_items": int(run.total_items or 0),
            "excluded_items": int(run.excluded_items or 0),
        }

    def _enqueue_job_enriched_event(
        self, *, run: EnrichmentRun, item: EnrichmentRunItem
    ) -> None:
        self.event_outbox_repository.enqueue(
            self.db,
            topic=STREAM_JOB_LIFECYCLE,
            aggregate_type="job",
            aggregate_id=str(item.job_id),
            event_type="job.enriched",
            payload={
                "run_id": run.id,
                "job_id": str(item.job_id),
                "source_type": run.source_type,
                "crawl_job_id": str(run.trigger_crawl_job_id)
                if run.trigger_crawl_job_id
                else None,
            },
            source_service="enrichment-worker",
            auto_commit=False,
        )

    async def execute_run(
        self, run_id: str, enrichment_service=None, *, claim: bool = True
    ) -> EnrichmentRun:
        """Execute a persisted run and update item/run status from enrichment results."""
        from app.services.ai_enrichment_service import get_ai_enrichment_service

        service = enrichment_service or get_ai_enrichment_service()

        if claim:
            claimed_run = self.claim_run(run_id)
            if claimed_run is None:
                run = self.get_run(run_id)
                if run is None:
                    raise ValueError(f"Enrichment run not found: {run_id}")
                return run

        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        items = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.run_id == run.id)
            .filter(EnrichmentRunItem.status == "pending")
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )
        if claim:
            self._sync_linked_crawl_job_ai_metrics(run)
            self.db.commit()
        if not claim:
            if run.status != "running":
                return run
            self._sync_linked_crawl_job_ai_metrics(run)
            self.db.commit()

        concurrency = self._resolve_run_concurrency()
        item_queue: asyncio.Queue[EnrichmentRunItem] = asyncio.Queue()
        for item in items:
            item_queue.put_nowait(item)

        try:

            async def worker() -> None:
                while True:
                    try:
                        item = item_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return

                    job = self.db.get(Job, item.job_id)
                    preflight_reason: str | None
                    if job is None:
                        preflight_reason = "JOB_NOT_FOUND"
                    else:
                        preflight = self.taxonomy_preflight.inspect(job)
                        preflight_reason = preflight.reason
                    if preflight_reason is not None:
                        self._update_item_excluded(
                            run_id,
                            item.id,
                            preflight_reason,
                        )
                        item_queue.task_done()
                        continue

                    job_title = self._get_job_title(item.job_id)
                    if self._update_item_started(run_id, item.id, job_title) is None:
                        item_queue.task_done()
                        continue

                    try:
                        result = await service.enrich_job_id(item.job_id)
                    except Exception as exc:
                        result = {
                            "job_id": str(item.job_id),
                            "status": "error",
                            "error": str(exc),
                        }

                    self._update_item_finished(run_id, item.id, result)
                    item_queue.task_done()

            workers = [
                asyncio.create_task(worker())
                for _ in range(min(concurrency, len(items) or 1))
            ]
            await asyncio.gather(*workers)
        except Exception as exc:
            error_message = str(exc)
            self.db.rollback()
            self.mark_run_failed(run_id, error_message)
            self.db.commit()
            raise

        self.db.expire_all()
        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        if run.status == "stopping":
            run = self._finalize_stopping_run(run)
            self.db.commit()
            return run
        if run.status in TERMINAL_RUN_STATUSES:
            return run

        counts = self._count_items_by_status(run_id)
        completed_items = counts["completed"]
        failed_items = counts["failed"]
        excluded_items = counts["excluded"]
        if failed_items > 0:
            run.status = "completed_with_failures"
        elif excluded_items > 0:
            run.status = "completed_with_exclusions"
        else:
            run.status = "completed"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        run.cancelled_items = counts["cancelled"]
        run.excluded_items = excluded_items
        run.current_job_title = None
        run.error_message = (
            None if failed_items == 0 else f"{failed_items} item(s) failed"
        )
        run.completed_at = utc_now()
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.flush()
        self.promote_next_ready_waiting_run()
        self.db.commit()
        return run

    def create_retry_run_from_failed_items(
        self, run_id: str
    ) -> Optional[EnrichmentRun]:
        """Create a new retry run from failed items in an earlier run."""
        self._require_active_slot()
        failed_item_rows = (
            self.db.query(
                EnrichmentRun.id.label("run_id"),
                EnrichmentRunItem,
            )
            .select_from(EnrichmentRun)
            .outerjoin(
                EnrichmentRunItem,
                and_(
                    EnrichmentRunItem.run_id == EnrichmentRun.id,
                    EnrichmentRunItem.status == "failed",
                ),
            )
            .filter(EnrichmentRun.id == run_id)
            .order_by(
                EnrichmentRunItem.position.asc(),
                EnrichmentRunItem.id.asc(),
            )
            .all()
        )
        if not failed_item_rows:
            return None

        failed_items = [item for _, item in failed_item_rows if item is not None]
        if not failed_items:
            raise ValueError(f"Run {run_id} has no failed items to retry")
        return self._create_run(
            source_type="retry_failed",
            job_ids=[str(item.job_id) for item in failed_items],
        )
