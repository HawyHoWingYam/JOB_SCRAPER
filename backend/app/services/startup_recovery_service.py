from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.crawl_job_listing import CrawlJobListing
from app.models.company_enrichment_run import CompanyEnrichmentRun, CompanyEnrichmentRunItem
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.sources.offertoday.completeness import is_complete_offertoday_job
from app.utils.time import utc_now

AI_RESTART_MESSAGE = "Service restarted before AI enrichment run could finish."
COMPANY_RESTART_MESSAGE = "Service restarted before company enrichment run could finish."
CRAWL_JOB_RESTART_MESSAGE = "Service restarted before crawl job could finish."
SCHEDULE_RESTART_MESSAGE = "Service restarted before scheduled scrape execution could finish."
ACTIVE_SCHEDULE_EXECUTION_STATUSES = ("pending", "running", "ai_running")
ACTIVE_AI_RUN_STATUSES = ("pending", "running")
ACTIVE_COMPANY_RUN_STATUSES = ("pending", "running")
# Manual-action-required crawl jobs are intentionally left resumable and must not
# be collapsed into startup recovery failures.
ACTIVE_CRAWL_JOB_STATUSES = ("dispatching", "running")

logger = logging.getLogger(__name__)


class StartupRecoveryService:
    """Convert interrupted in-process work into explicit terminal failure states on startup."""

    def __init__(self, db: Session):
        self.db = db
        self.crawl_job_repository = CrawlJobRepository()

    def recover_interrupted_operations(
        self,
        *,
        recover_ai_runs: bool = True,
        recover_company_runs: bool = True,
        recover_crawl_jobs: bool = True,
        recover_schedule_executions: bool = True,
    ) -> dict[str, int]:
        ai_run_count = 0
        if recover_ai_runs:
            ai_run_count = self._recover_ai_runs()

        company_run_count = 0
        if recover_company_runs:
            company_run_count = self._recover_company_runs()

        self.db.commit()

        crawl_job_recovery_count = 0
        if recover_crawl_jobs:
            try:
                crawl_job_recovery_count = self._recover_crawl_jobs()
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("Startup crawl job recovery failed")

        schedule_recovery_count = 0
        if recover_schedule_executions:
            try:
                schedule_recovery_count = self._recover_schedule_executions()
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("Startup schedule execution recovery failed")

        return {
            "ai_runs_recovered": ai_run_count,
            "company_runs_recovered": company_run_count,
            "crawl_jobs_recovered": crawl_job_recovery_count,
            "schedule_executions_recovered": schedule_recovery_count,
        }

    def recover_ai_runs_only(self) -> int:
        ai_run_count = self._recover_ai_runs()
        self.db.commit()
        return ai_run_count

    def _recover_ai_runs(self) -> int:
        active_runs = (
            self.db.query(EnrichmentRun)
            .filter(EnrichmentRun.status.in_(ACTIVE_AI_RUN_STATUSES))
            .all()
        )
        timestamp = utc_now()
        if not active_runs:
            return 0

        recovered_runs = 0
        for run in active_runs:
            items = (
                self.db.query(EnrichmentRunItem)
                .filter(EnrichmentRunItem.run_id == run.id)
                .all()
            )
            if not self._enrichment_run_was_started(run, items=items):
                continue
            completed_items = 0
            failed_items = 0

            for item in items:
                if item.status == "completed":
                    completed_items += 1
                    continue

                item.status = "failed"
                item.error_message = AI_RESTART_MESSAGE
                item.started_at = item.started_at or timestamp
                item.completed_at = item.completed_at or timestamp
                failed_items += 1

            run.status = "failed" if completed_items == 0 else "completed_with_failures"
            run.pending_items = 0
            run.completed_items = completed_items
            run.failed_items = failed_items
            run.started_at = run.started_at or timestamp
            run.completed_at = timestamp
            run.current_job_title = None
            run.error_message = AI_RESTART_MESSAGE

            recovered_runs += 1

        return recovered_runs

    def _enrichment_run_was_started(self, run: EnrichmentRun, *, items: list[EnrichmentRunItem]) -> bool:
        if str(run.status or "").lower() == "running":
            return True
        if run.started_at is not None:
            return True
        return any(
            item.status != "pending"
            or item.started_at is not None
            or item.completed_at is not None
            for item in items
        )

    def _recover_company_runs(self) -> int:
        active_runs = (
            self.db.query(CompanyEnrichmentRun)
            .filter(CompanyEnrichmentRun.status.in_(ACTIVE_COMPANY_RUN_STATUSES))
            .all()
        )
        timestamp = utc_now()
        if not active_runs:
            return 0

        for run in active_runs:
            items = (
                self.db.query(CompanyEnrichmentRunItem)
                .filter(CompanyEnrichmentRunItem.run_id == run.id)
                .all()
            )
            completed_items = 0
            failed_items = 0

            for item in items:
                if item.status == "completed":
                    completed_items += 1
                    continue

                item.status = "failed"
                item.error_message = item.error_message or COMPANY_RESTART_MESSAGE
                item.started_at = item.started_at or timestamp
                item.completed_at = item.completed_at or timestamp
                failed_items += 1

            run.status = "failed" if completed_items == 0 else "completed_with_failures"
            run.pending_items = 0
            run.completed_items = completed_items
            run.failed_items = failed_items
            run.started_at = run.started_at or timestamp
            run.completed_at = timestamp
            run.current_company_name = None
            run.error_message = COMPANY_RESTART_MESSAGE

        return len(active_runs)

    def _recover_crawl_jobs(self) -> int:
        inspector = inspect(self.db.get_bind())
        if "crawl_jobs" not in inspector.get_table_names():
            return 0

        table_names = set(inspector.get_table_names())
        managed_job_ids = set()
        if "crawl_job_executions" in table_names:
            managed_job_ids = {
                row[0]
                for row in self.db.query(CrawlJobExecution.crawl_job_id)
                .filter(
                    CrawlJobExecution.status.in_(
                        ["launching", "running", "stop_requested"]
                    )
                )
                .all()
            }

        active_query = self.db.query(CrawlJob).filter(
            CrawlJob.status.in_(ACTIVE_CRAWL_JOB_STATUSES)
        )
        if managed_job_ids:
            active_query = active_query.filter(CrawlJob.id.notin_(managed_job_ids))
        active_jobs = (
            active_query
            .order_by(CrawlJob.created_at.asc(), CrawlJob.id.asc())
            .all()
        )
        if not active_jobs:
            return 0

        timestamp = utc_now()
        recovered_job_ids = [job.id for job in active_jobs]
        for crawl_job in active_jobs:
            crawl_job.status = "failed"
            crawl_job.completed_at = crawl_job.completed_at or timestamp
            crawl_job.error_message = CRAWL_JOB_RESTART_MESSAGE

        recovery_records_by_job_id: dict[object, list[dict[str, object]]] = (
            defaultdict(list)
        )
        if "crawl_job_listings" in table_names:
            running_listings = (
                self.db.query(CrawlJobListing)
                .filter(
                    CrawlJobListing.last_detail_crawl_job_id.in_(recovered_job_ids),
                    CrawlJobListing.detail_status == "running",
                )
                .order_by(
                    CrawlJobListing.last_detail_crawl_job_id.asc(),
                    CrawlJobListing.source_site.asc(),
                    CrawlJobListing.source_job_id.asc(),
                    CrawlJobListing.created_at.asc(),
                    CrawlJobListing.id.asc(),
                )
                .all()
            )

            offertoday_source_job_ids = sorted(
                {
                    row.source_job_id
                    for row in running_listings
                    if row.source_site == "offertoday"
                }
            )
            offertoday_jobs_by_source_id: dict[str, Job] = {}
            if offertoday_source_job_ids and "jobs" in table_names:
                offertoday_jobs = (
                    self.db.query(Job)
                    .filter(
                        Job.source_site == "offertoday",
                        Job.source_job_id.in_(offertoday_source_job_ids),
                        Job.is_deleted.is_(False),
                    )
                    .all()
                )
                offertoday_jobs_by_source_id = {
                    job.source_job_id: job for job in offertoday_jobs
                }

            for listing in running_listings:
                before_status = listing.detail_status
                existing_job = (
                    offertoday_jobs_by_source_id.get(listing.source_job_id)
                    if listing.source_site == "offertoday"
                    else None
                )
                if existing_job is not None and is_complete_offertoday_job(
                    existing_job
                ):
                    listing.detail_status = "completed"
                    listing.published_job_id = existing_job.id
                    listing.detail_payload = deepcopy(
                        dict(existing_job.raw_data or {})
                    )
                    listing.detail_error_message = None
                    outcome = "reconciled_existing_job"
                else:
                    listing.detail_status = "failed"
                    listing.published_job_id = None
                    listing.detail_error_message = CRAWL_JOB_RESTART_MESSAGE
                    outcome = (
                        "interrupted_retryable"
                        if listing.source_site == "offertoday"
                        else "interrupted_failed"
                    )
                listing.detail_completed_at = timestamp

                published_job_id = listing.published_job_id
                recovery_records_by_job_id[
                    listing.last_detail_crawl_job_id
                ].append(
                    {
                        "listing_id": str(listing.id),
                        "source_site": listing.source_site,
                        "source_job_id": listing.source_job_id,
                        "before_status": before_status,
                        "after_status": listing.detail_status,
                        "outcome": outcome,
                        "published_job_id": (
                            str(published_job_id)
                            if published_job_id is not None
                            else None
                        ),
                        "counts_as_fetch_success": False,
                    }
                )

        for crawl_job in active_jobs:
            records = recovery_records_by_job_id.get(crawl_job.id, [])
            if not records:
                continue
            self.crawl_job_repository.append_event(
                self.db,
                crawl_job_id=crawl_job.id,
                event_type="crawl.detail_recovered",
                payload={"records": records},
                emitted_by="startup-recovery",
                auto_commit=False,
            )

        return len(active_jobs)

    def _recover_schedule_executions(self) -> int:
        inspector = inspect(self.db.get_bind())
        available_columns = {
            column["name"]
            for column in inspector.get_columns("schedule_executions")
        }
        if "id" not in available_columns or "status" not in available_columns:
            return 0

        select_columns = ["id", "status"]
        for optional_column in ("started_at", "completed_at", "duration_seconds"):
            if optional_column in available_columns:
                select_columns.append(optional_column)

        rows = self.db.execute(
            text(
                f"""
                SELECT {", ".join(select_columns)}
                FROM schedule_executions
                WHERE status IN ('pending', 'running', 'ai_running')
                """
            )
        ).mappings().all()

        recovery_timestamp = utc_now()
        for row in rows:
            updates = {
                "status": "failed",
            }
            if "completed_at" in available_columns:
                updates["completed_at"] = row.get("completed_at") or recovery_timestamp
            if "error_message" in available_columns:
                updates["error_message"] = SCHEDULE_RESTART_MESSAGE
            if "duration_seconds" in available_columns and row.get("duration_seconds") is None:
                started_at = row.get("started_at")
                completed_at = updates.get("completed_at")
                if started_at is not None and completed_at is not None:
                    try:
                        updates["duration_seconds"] = max(
                            0,
                            int((completed_at - started_at).total_seconds()),
                        )
                    except TypeError:
                        updates["duration_seconds"] = None

            assignments = ", ".join(f"{column} = :{column}" for column in updates)
            self.db.execute(
                text(f"UPDATE schedule_executions SET {assignments} WHERE id = :execution_id"),
                {"execution_id": row["id"], **updates},
            )

        return len(rows)
