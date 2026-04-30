import uuid
from datetime import timedelta
from typing import List, Optional

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.utils.time import utc_now

ACTIVE_RUN_STATUSES = ("pending", "running")


class EnrichmentRunService:
    """Persist enrichment runs and their items."""

    def __init__(self, db: Session):
        self.db = db

    def create_post_scrape_run(self, job_ids: List[str]) -> EnrichmentRun:
        """Persist a post-scrape run for internal `jobs.id` UUID values."""
        return self._create_run(source_type="post_scrape", job_ids=job_ids)

    def _create_run(self, source_type: str, job_ids: List[str]) -> EnrichmentRun:
        """Persist a run and its pending items for internal `jobs.id` UUID values."""
        normalized_job_ids = [str(job_id) for job_id in job_ids]
        item_count = len(normalized_job_ids)
        run = EnrichmentRun(
            source_type=source_type,
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

    def create_manual_pending_run(self, limit: Optional[int] = None) -> Optional[EnrichmentRun]:
        """Create a manual run from globally pending unenriched jobs."""
        query = (
            self.db.query(Job.id)
            .filter(
                Job.ai_enriched_at.is_(None),
                Job.is_deleted == False,
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)

        job_ids = [str(row.id) for row in query.all()]
        if not job_ids:
            return None
        return self._create_run(source_type="manual_pending", job_ids=job_ids)

    def get_run(self, run_id: str) -> Optional[EnrichmentRun]:
        """Fetch a persisted run by ID."""
        return (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.id == run_id)
            .first()
        )

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
        ordered_runs = self.db.query(EnrichmentRun).order_by(
            EnrichmentRun.created_at.desc(),
            EnrichmentRun.id.desc(),
        )
        newest_active_run = (
            ordered_runs
            .filter(EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES))
            .first()
        )
        if newest_active_run is not None:
            previous_run = (
                self.db.query(EnrichmentRun)
                .filter(
                    or_(
                        EnrichmentRun.created_at > newest_active_run.created_at,
                        and_(
                            EnrichmentRun.created_at == newest_active_run.created_at,
                            EnrichmentRun.id > newest_active_run.id,
                        ),
                    )
                )
                .order_by(
                    EnrichmentRun.created_at.asc(),
                    EnrichmentRun.id.asc(),
                )
                .first()
            )
            if previous_run is not None:
                return [previous_run, newest_active_run]

            next_run = (
                self.db.query(EnrichmentRun)
                .filter(
                    or_(
                        EnrichmentRun.created_at < newest_active_run.created_at,
                        and_(
                            EnrichmentRun.created_at == newest_active_run.created_at,
                            EnrichmentRun.id < newest_active_run.id,
                        ),
                    )
                )
                .order_by(
                    EnrichmentRun.created_at.desc(),
                    EnrichmentRun.id.desc(),
                )
                .first()
            )
            return [newest_active_run] + ([next_run] if next_run is not None else [])

        return (
            ordered_runs
            .filter(EnrichmentRun.status.notin_(ACTIVE_RUN_STATUSES))
            .limit(2)
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

    def get_overview(self) -> dict:
        """Return AI enrichment overview counters and last completed run."""
        total_jobs = self.db.query(Job).filter(Job.is_deleted == False).count()
        enriched_jobs = (
            self.db.query(Job)
            .filter(
                Job.ai_enriched_at.isnot(None),
                Job.is_deleted == False,
            )
            .count()
        )
        running_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status == "running")
            .count()
        )
        active_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status.in_(ACTIVE_RUN_STATUSES))
            .count()
        )
        failed_items = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.status == "failed")
            .count()
        )
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
            "failed_items": failed_items,
            "last_completed_run": last_completed_run,
        }

    async def execute_run(self, run_id: str, enrichment_service=None) -> EnrichmentRun:
        """Execute a persisted run and update item/run status from enrichment results."""
        from app.services.ai_enrichment_service import get_ai_enrichment_service

        run = self.db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
        items = (
            self.db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.run_id == run.id)
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )

        service = enrichment_service or get_ai_enrichment_service()

        def _job_id_param(job_id: uuid.UUID):
            dialect = self.db.get_bind().dialect.name
            if dialect == "sqlite":
                return job_id.hex
            return job_id

        def _get_job_title(job_id: uuid.UUID) -> Optional[str]:
            row = self.db.execute(
                text("SELECT title FROM jobs WHERE id = :job_id"),
                {"job_id": _job_id_param(job_id)},
            ).first()
            return row[0] if row else None

        now = utc_now()
        run.status = "running"
        run.started_at = run.started_at or now
        run.completed_at = None
        run.error_message = None
        run.current_job_title = None

        # Persist the "run started" state so a separate request can observe it.
        self.db.commit()

        completed_items = 0
        failed_items = 0

        try:
            for index, item in enumerate(items):
                item.status = "running"
                item.started_at = item.started_at or utc_now()
                run.current_job_title = _get_job_title(item.job_id)

                # Persist the running item before doing any work.
                self.db.commit()

                result = await service.enrich_job_ids([item.job_id])
                job_result = {}
                for payload in result.get("jobs", []) if isinstance(result, dict) else []:
                    if payload.get("job_id") is None:
                        continue
                    if str(payload.get("job_id")) == str(item.job_id):
                        job_result = payload
                        break
                if not job_result and isinstance(result, dict) and result.get("jobs"):
                    job_result = result["jobs"][0] or {}

                if job_result.get("status") == "success":
                    item.status = "completed"
                    item.error_message = None
                    completed_items += 1
                else:
                    item.status = "failed"
                    item.error_message = job_result.get("error") or "missing result for run item"
                    failed_items += 1
                item.completed_at = utc_now()

                run.completed_items = completed_items
                run.failed_items = failed_items
                run.pending_items = run.total_items - completed_items - failed_items
                run.current_job_title = None

                # Persist item completion and run counters immediately.
                self.db.commit()
        except Exception as exc:
            timestamp = utc_now()
            error_message = str(exc)
            latest_failure_timestamp = timestamp
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

            self.db.commit()
            raise

        run.status = "completed" if failed_items == 0 else "completed_with_failures"
        run.pending_items = 0
        run.completed_items = completed_items
        run.failed_items = failed_items
        run.current_job_title = None
        run.error_message = None if failed_items == 0 else f"{failed_items} item(s) failed"
        run.completed_at = utc_now()
        self.db.commit()
        return run

    def create_retry_run_from_failed_items(self, run_id: str) -> EnrichmentRun:
        """Create a new retry run from failed items in an earlier run."""
        failed_items = (
            self.db.query(EnrichmentRunItem)
            .filter(
                EnrichmentRunItem.run_id == run_id,
                EnrichmentRunItem.status == "failed",
            )
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )
        if not failed_items:
            raise ValueError(f"Run {run_id} has no failed items to retry")
        return self._create_run(
            source_type="retry_failed",
            job_ids=[str(item.job_id) for item in failed_items],
        )
