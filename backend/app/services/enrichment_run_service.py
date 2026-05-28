import uuid
import asyncio
from dataclasses import dataclass
from datetime import timedelta
import re
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, case, func, or_, text
from sqlalchemy.orm import Session

from app.messaging.topics import STREAM_JOB_LIFECYCLE
from app.models.crawl_job import CrawlJob
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job_skill import JobSkill
from app.models.job_skill_mention import JobSkillMention
from app.models.job import Job
from app.models.skill import Skill
from app.models.skill_category import SkillCategory
from app.models.skill_review_candidate import SkillReviewCandidate
from app.models.skill_technology import SkillTechnology
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.utils.time import utc_now

ACTIVE_RUN_STATUSES = ("pending", "running")
_REVIEW_KEY_PATTERN = re.compile(r"[^a-z0-9+#./\-\s]+")
_LOOKUP_KEY_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_unicode(value: str) -> str:
    text_value = str(value or "").strip()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text_value = text_value.replace(dash, "-")
    return re.sub(r"\s+", " ", text_value)


def _normalize_lookup_key(value: str) -> str:
    text_value = _normalize_unicode(value).lower().strip()
    text_value = _LOOKUP_KEY_PATTERN.sub(" ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def _normalize_review_candidate_key(value: str) -> str:
    text_value = _normalize_unicode(value).lower().strip()
    text_value = _REVIEW_KEY_PATTERN.sub(" ", text_value)
    text_value = re.sub(r"\s*([+#./-])\s*", r"\1", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


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


class EnrichmentRunService:
    """Persist enrichment runs and their items."""

    def __init__(self, db: Session):
        self.db = db
        self.crawl_job_repository = CrawlJobRepository()
        self.event_outbox_repository = EventOutboxRepository()

    def create_post_scrape_run(self, job_ids: List[str]) -> EnrichmentRun:
        """Persist a post-scrape run for internal `jobs.id` UUID values."""
        return self._create_run(source_type="post_scrape", job_ids=job_ids)

    def _create_run(
        self,
        source_type: str,
        job_ids: List[str],
        *,
        trigger_crawl_job_id: str | uuid.UUID | None = None,
    ) -> EnrichmentRun:
        """Persist a run and its pending items for internal `jobs.id` UUID values."""
        normalized_job_ids = [str(job_id) for job_id in job_ids]
        item_count = len(normalized_job_ids)
        run = EnrichmentRun(
            source_type=source_type,
            trigger_crawl_job_id=uuid.UUID(str(trigger_crawl_job_id)) if trigger_crawl_job_id else None,
            status="pending",
            job_ids=normalized_job_ids,
            total_items=item_count,
            pending_items=item_count,
            completed_items=0,
            failed_items=0,
        )
        self.db.add(run)
        self.db.flush()

        for position, job_id in enumerate(normalized_job_ids):
            self.db.add(
                EnrichmentRunItem(
                    run_id=run.id,
                    job_id=uuid.UUID(job_id),
                    position=position,
                    status="pending",
                )
            )

        self.db.flush()
        return run

    def create_post_scrape_run_for_batch(self, job_ids: List[str]) -> Optional[EnrichmentRun]:
        """Create a post-scrape run only when the scrape batch persisted rows."""
        if not job_ids:
            return None

        return self.create_post_scrape_run(job_ids=job_ids)

    def create_manual_batch_run(self, job_ids: List[str]) -> Optional[EnrichmentRun]:
        """Create a manually requested run for an explicit job ID batch."""
        if not job_ids:
            return None
        return self._create_run(source_type="manual_batch", job_ids=job_ids)

    def create_manual_single_job_run(self, job_id: str) -> EnrichmentRun:
        """Create a worker-owned run for a single explicitly requested job."""
        return self._create_run(source_type="manual_single", job_ids=[job_id])

    def create_manual_query_run(
        self,
        *,
        review_candidate_names: Optional[List[str]] = None,
        polluted_skill_names: Optional[List[str]] = None,
        source_subclassification_names: Optional[List[str]] = None,
        scope: str = "all",
    ) -> Optional[EnrichmentRun]:
        """Create a manual run from governance-oriented selectors."""
        job_ids = self._select_manual_query_job_ids(
            review_candidate_names=review_candidate_names,
            polluted_skill_names=polluted_skill_names,
            source_subclassification_names=source_subclassification_names,
            scope=scope,
        )
        if not job_ids:
            return None
        return self._create_run(source_type="manual_query", job_ids=job_ids)

    def create_manual_pending_run(self, limit: Optional[int] = None) -> Optional[EnrichmentRun]:
        """Create a manual run from globally pending unenriched jobs."""
        query = (
            self.db.query(Job.id)
            .filter(
                Job.ai_enriched_at.is_(None),
                Job.is_deleted == False,
                Job.source_classification_id.isnot(None),
                Job.source_classification_id != "",
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)

        job_ids = [str(row.id) for row in query.all()]
        if not job_ids:
            return None
        return self._create_run(source_type="manual_pending", job_ids=job_ids)

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

    def append_job_to_crawl_auto_run(self, *, crawl_job_id: str, job_id: str) -> CrawlAutoRunAppendResult:
        crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        job_uuid = uuid.UUID(str(job_id))
        run = self.get_crawl_auto_run(str(crawl_job_uuid))
        if run is None:
            run = self._create_run(
                source_type="crawl_auto",
                job_ids=[],
                trigger_crawl_job_id=crawl_job_uuid,
            )
            run.total_items = 0
            run.pending_items = 0
            run.completed_items = 0
            run.failed_items = 0
            run.job_ids = []
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

        if run.status != "pending":
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

    def request_run_execution(self, run_id: str, *, source_service: str = "ai-api") -> bool:
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

    def request_crawl_auto_run_if_ready(self, crawl_job_id: str) -> bool:
        crawl_job_uuid = uuid.UUID(str(crawl_job_id))
        crawl_job = (
            self.db.query(CrawlJob)
            .filter(CrawlJob.id == crawl_job_uuid)
            .first()
        )
        run = self.get_crawl_auto_run(str(crawl_job_uuid))
        if crawl_job is None or run is None:
            return False
        if run.status != "pending" or not run.total_items:
            return False
        if not AIRuntimeSettingsService(self.db).get_profile_runtime_metadata("jobs").is_ready:
            return False
        if crawl_job.status not in {"completed", "failed"}:
            return False

        metrics = dict(crawl_job.metrics or {})
        items_emitted = int(metrics.get("items_emitted") or 0)
        ingest_items_seen = int(metrics.get("ingest_items_seen") or 0)
        ingest_items_failed = int(metrics.get("ingest_items_failed") or 0)
        ingest_dead_lettered = int(metrics.get("ingest_dead_lettered") or 0)
        ingest_items_settled = ingest_items_seen + max(ingest_items_failed, ingest_dead_lettered)
        if items_emitted > 0 and ingest_items_settled < items_emitted:
            return False

        return self.request_run_execution(run.id, source_service="enrichment-worker")

    def _select_manual_query_job_ids(
        self,
        *,
        review_candidate_names: Optional[List[str]],
        polluted_skill_names: Optional[List[str]],
        source_subclassification_names: Optional[List[str]],
        scope: str,
    ) -> list[str]:
        normalized_review_names = self._normalize_selector_values(
            review_candidate_names,
            normalizer=_normalize_review_candidate_key,
        )
        normalized_polluted_names = self._normalize_selector_values(
            polluted_skill_names,
            normalizer=_normalize_lookup_key,
        )
        if not normalized_review_names and not normalized_polluted_names:
            raise ValueError("At least one query selector is required")

        if scope not in {"all", "enriched_only"}:
            raise ValueError(f"Unsupported query scope: {scope}")

        selected_job_ids: set[uuid.UUID] = set()
        review_candidate_ids = self._find_review_candidate_ids(normalized_review_names)
        if review_candidate_ids:
            selected_job_ids.update(
                job_id
                for (job_id,) in (
                    self.db.query(JobSkillMention.job_id)
                    .filter(
                        JobSkillMention.review_candidate_id.in_(review_candidate_ids),
                        JobSkillMention.resolution == "review_candidate",
                    )
                    .all()
                )
            )

        polluted_skill_ids = self._find_polluted_skill_ids(normalized_polluted_names)
        if polluted_skill_ids:
            selected_job_ids.update(
                job_id
                for (job_id,) in (
                    self.db.query(JobSkill.job_id)
                    .filter(JobSkill.skill_id.in_(polluted_skill_ids))
                    .all()
                )
            )

        if not selected_job_ids:
            return []

        query = self.db.query(Job.id).filter(
            Job.id.in_(selected_job_ids),
            Job.is_deleted == False,
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

        return [str(row.id) for row in query.order_by(Job.created_at.asc(), Job.id.asc()).all()]

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

        return {
            candidate.id
            for candidate in self.db.query(
                SkillReviewCandidate.id,
                SkillReviewCandidate.normalized_name,
            ).all()
            if _normalize_review_candidate_key(candidate.normalized_name or "") in normalized_names
        }

    def _find_polluted_skill_ids(self, normalized_names: set[str]) -> set[uuid.UUID]:
        if not normalized_names:
            return set()

        return {
            skill.id
            for skill in (
                self.db.query(Skill)
                .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
                .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
                .filter(
                    func.lower(SkillCategory.name) == "other",
                    func.lower(SkillTechnology.name) == "general",
                )
                .all()
            )
            if _normalize_lookup_key(skill.name) in normalized_names
        }

    def get_run(self, run_id: str) -> Optional[EnrichmentRun]:
        """Fetch a persisted run by ID."""
        return (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .first()
        )

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
        """Return the compact run slice needed by the two-card monitor."""
        ordered_runs = (
            self.db.query(
                EnrichmentRun.id.label("run_id"),
                func.row_number().over(
                    order_by=(
                        EnrichmentRun.created_at.desc(),
                        EnrichmentRun.id.desc(),
                    )
                ).label("overall_pos"),
                case(
                    (EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES), 1),
                    else_=0,
                ).label("is_active"),
            )
            .subquery()
        )
        ranked_runs = (
            self.db.query(
                ordered_runs.c.run_id,
                ordered_runs.c.overall_pos,
                func.min(
                    case(
                        (ordered_runs.c.is_active == 1, ordered_runs.c.overall_pos),
                        else_=None,
                    )
                ).over().label("active_pos"),
            )
            .subquery()
        )

        active_pos = ranked_runs.c.active_pos
        overall_pos = ranked_runs.c.overall_pos

        return (
            self.db.query(EnrichmentRun)
            .join(ranked_runs, ranked_runs.c.run_id == EnrichmentRun.id)
            .filter(
                or_(
                    and_(active_pos.is_(None), overall_pos <= 2),
                    and_(active_pos == 1, overall_pos <= 2),
                    and_(
                        active_pos > 1,
                        or_(
                            overall_pos == active_pos - 1,
                            overall_pos == active_pos,
                        ),
                    ),
                )
            )
            .order_by(overall_pos.asc())
            .all()
        )

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

    def mark_run_failed(self, run_id: str, error_message: str) -> Optional[EnrichmentRun]:
        """Persist a terminal failure state for a run when orchestration aborts."""
        run = self.get_run(run_id)
        if run is None:
            return None

        items = self.list_run_items(run_id)
        completed_items = 0
        failed_items = 0
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

        run.status = "failed" if completed_items == 0 else "completed_with_failures"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        if run.started_at is None:
            run.started_at = timestamp
        run.completed_at = latest_failure_timestamp
        run.current_job_title = None
        run.error_message = error_message
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

        for item in items:
            if item.status == "completed":
                completed_items += 1
                continue
            if item.status == "failed":
                failed_items += 1
                continue

            item.status = "cancelled"
            item.error_message = error_message
            if item.started_at is None:
                item.started_at = timestamp
            item.completed_at = timestamp

        run.status = "cancelled"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        if run.started_at is None:
            run.started_at = timestamp
        run.completed_at = timestamp
        run.current_job_title = None
        run.error_message = error_message
        self.db.flush()
        return run

    def get_overview(self) -> dict:
        """Return AI enrichment overview counters and last completed run."""
        total_jobs, enriched_jobs = (
            self.db.query(
                func.count(Job.id),
                func.count(Job.ai_enriched_at),
            )
            .filter(Job.is_deleted == False)
            .one()
        )
        running_runs, active_runs = (
            self.db.query(
                func.coalesce(
                    func.sum(case((EnrichmentRun.status == "running", 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES), 1), else_=0)),
                    0,
                ),
            )
            .one()
        )
        failed_items = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.status == "failed")
            .count()
        )
        failed_jobs = self._count_current_failed_jobs() if failed_items > 0 else 0
        last_completed_run = (
            self.db.query(EnrichmentRun)
            .filter(
                EnrichmentRun.status.in_(["completed", "completed_with_failures"])
            )
            .order_by(
                EnrichmentRun.completed_at.desc(),
                EnrichmentRun.created_at.desc(),
            )
            .first()
        )

        return {
            "total_jobs": total_jobs,
            "enriched_jobs": enriched_jobs,
            "pending_jobs": total_jobs - enriched_jobs,
            "running_runs": running_runs,
            "active_runs": active_runs,
            "failed_jobs": failed_jobs,
            "failed_items": failed_items,
            "last_completed_run": last_completed_run,
        }

    def _count_current_failed_jobs(self) -> int:
        latest_item_per_job = (
            self.db.query(
                EnrichmentRunItem.job_id.label("job_id"),
                EnrichmentRunItem.status.label("status"),
                func.row_number().over(
                    partition_by=EnrichmentRunItem.job_id,
                    order_by=(
                        EnrichmentRunItem.created_at.desc(),
                        EnrichmentRunItem.id.desc(),
                    ),
                ).label("row_number"),
            )
            .subquery()
        )

        return int(
            self.db.query(func.count())
            .select_from(latest_item_per_job)
            .join(Job, Job.id == latest_item_per_job.c.job_id)
            .filter(
                latest_item_per_job.c.row_number == 1,
                latest_item_per_job.c.status == "failed",
                Job.ai_enriched_at.is_(None),
                Job.is_deleted == False,
            )
            .scalar()
            or 0
        )

    def _compute_in_progress_items(self, run: EnrichmentRun) -> int:
        if run.status not in ACTIVE_RUN_STATUSES:
            return 0
        in_progress = run.total_items - run.pending_items - run.completed_items - run.failed_items
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
            "current_job_title": run.current_job_title,
            "in_progress_items": self._compute_in_progress_items(run),
        }

    def _count_items_by_status(self, run_id: str) -> Dict[str, int]:
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
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

    def _update_item_started(self, run_id: str, item_id: str, job_title: Optional[str]) -> Dict[str, object]:
        timestamp = utc_now()
        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        item = self.db.query(EnrichmentRunItem).filter(EnrichmentRunItem.id == item_id).one()

        item.status = "running"
        item.started_at = item.started_at or timestamp
        run.current_job_title = job_title
        run.error_message = None
        counts = self._count_items_by_status(run_id)
        run.pending_items = counts["pending"]
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        self.db.commit()
        return self._serialize_run_progress(run_id)

    def _update_item_finished(self, run_id: str, item_id: str, result: Dict[str, object]) -> Dict[str, object]:
        timestamp = utc_now()
        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        item = self.db.query(EnrichmentRunItem).filter(EnrichmentRunItem.id == item_id).one()

        if result.get("status") == "success":
            item.status = "completed"
            item.error_message = None
            self._enqueue_job_enriched_event(run=run, item=item)
        else:
            item.status = "failed"
            item.error_message = str(result.get("error") or "missing result for run item")

        item.completed_at = timestamp

        counts = self._count_items_by_status(run_id)
        run.completed_items = counts["completed"]
        run.failed_items = counts["failed"]
        run.pending_items = counts["pending"]
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
            "trigger_crawl_job_id": str(run.trigger_crawl_job_id) if run.trigger_crawl_job_id else None,
            "total_items": int(run.total_items or 0),
        }

    def _enqueue_job_enriched_event(self, *, run: EnrichmentRun, item: EnrichmentRunItem) -> None:
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
                "crawl_job_id": str(run.trigger_crawl_job_id) if run.trigger_crawl_job_id else None,
            },
            source_service="enrichment-worker",
            auto_commit=False,
        )

    async def execute_run(self, run_id: str, enrichment_service=None, *, claim: bool = True) -> EnrichmentRun:
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
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )
        if claim:
            self._sync_linked_crawl_job_ai_metrics(run)
            self.db.commit()
        if not claim:
            now = utc_now()
            run.status = "running"
            run.started_at = run.started_at or now
            run.completed_at = None
            run.error_message = None
            run.current_job_title = None
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

                    job_title = self._get_job_title(item.job_id)
                    self._update_item_started(run_id, item.id, job_title)

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

            workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(items) or 1))]
            await asyncio.gather(*workers)
        except Exception as exc:
            timestamp = utc_now()
            error_message = str(exc)
            latest_failure_timestamp = timestamp
            items = (
                self.db.query(EnrichmentRunItem)
                .filter(EnrichmentRunItem.run_id == run_id)
                .order_by(EnrichmentRunItem.position.asc())
                .all()
            )
            running_items = [item for item in items if item.status == "running"]
            pending_items = [item for item in items if item.status == "pending"]

            for item in pending_items:
                item.status = "failed"
                item.error_message = error_message
                item.started_at = item.started_at or timestamp
                item.completed_at = timestamp

            for offset, item in enumerate(running_items, start=1):
                failure_timestamp = timestamp + timedelta(microseconds=offset)
                item.status = "failed"
                item.error_message = error_message
                item.started_at = item.started_at or timestamp
                item.completed_at = failure_timestamp
                latest_failure_timestamp = failure_timestamp

            completed_items = sum(item.status == "completed" for item in items)
            failed_items = sum(item.status == "failed" for item in items)

            run.status = "failed" if completed_items == 0 else "completed_with_failures"
            run.pending_items = 0
            run.completed_items = completed_items
            run.failed_items = failed_items
            run.completed_at = latest_failure_timestamp
            run.current_job_title = None
            run.error_message = error_message
            self._sync_linked_crawl_job_ai_metrics(run)

            self.db.commit()
            raise

        self.db.expire_all()
        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        completed_items = run.completed_items
        failed_items = run.failed_items
        run.status = "completed" if failed_items == 0 else "completed_with_failures"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        run.current_job_title = None
        run.error_message = None if failed_items == 0 else f"{failed_items} item(s) failed"
        run.completed_at = utc_now()
        self._sync_linked_crawl_job_ai_metrics(run)
        self.db.commit()
        return run

    def create_retry_run_from_failed_items(self, run_id: str) -> Optional[EnrichmentRun]:
        """Create a new retry run from failed items in an earlier run."""
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
