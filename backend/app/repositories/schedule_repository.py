"""
Schedule Repository - Data access layer for Schedule entities.

Handles schedule and execution CRUD operations.
"""

import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from uuid import UUID

from app.crawl_phases import resolve_crawl_phase
from app.crawl_modes import resolve_crawl_mode
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.schemas.schedule import normalize_source_site
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class ScheduleRepository:
    """Repository for Schedule database operations."""

    SUPPORTED_SOURCE_SITES = {"jobsdb", "ctgoodjobs", "offertoday"}

    def _normalize_source_site_and_activation(self, schedule_data: dict) -> dict:
        """Force unsupported source sites inactive during the transitional phase."""
        normalized = dict(schedule_data)
        raw_source_site = normalized.get("source_site")
        source_site = normalize_source_site(raw_source_site)
        normalized["source_site"] = source_site
        normalized["crawl_phase"] = resolve_crawl_phase(normalized.get("crawl_phase"))
        normalized["crawl_mode"] = resolve_crawl_mode(source_site, normalized.get("crawl_mode"))
        if source_site not in self.SUPPORTED_SOURCE_SITES:
            normalized["is_active"] = False
        return normalized

    # ============== Schedule Operations ==============

    def get_all_schedules(
        self, db: Session, skip: int = 0, limit: int = 100
    ) -> List[ScrapeSchedule]:
        """Get all schedules with pagination."""
        schedules = (
            db.query(ScrapeSchedule)
            .order_by(desc(ScrapeSchedule.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
        self._attach_latest_execution_summaries(db, schedules)
        return schedules

    def get_active_schedules(self, db: Session) -> List[ScrapeSchedule]:
        """Get all active schedules."""
        return (
            db.query(ScrapeSchedule)
            .filter(ScrapeSchedule.is_active == True)
            .all()
        )

    def get_schedule_by_id(
        self, db: Session, schedule_id: UUID
    ) -> Optional[ScrapeSchedule]:
        """Get schedule by ID."""
        return db.query(ScrapeSchedule).filter(ScrapeSchedule.id == schedule_id).first()

    def create_schedule(
        self, db: Session, schedule_data: dict
    ) -> ScrapeSchedule:
        """Create a new schedule."""
        try:
            schedule_data = dict(schedule_data)
            schedule_data.setdefault("source_site", "jobsdb")
            schedule_data = self._normalize_source_site_and_activation(schedule_data)
            schedule = ScrapeSchedule(**schedule_data)
            db.add(schedule)
            db.commit()
            db.refresh(schedule)
            logger.info(f"Created schedule: {schedule.name}")
            return schedule
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating schedule: {e}")
            raise

    def update_schedule(
        self, db: Session, schedule_id: UUID, update_data: dict
    ) -> Optional[ScrapeSchedule]:
        """Update an existing schedule."""
        try:
            schedule = self.get_schedule_by_id(db, schedule_id)
            if not schedule:
                return None

            update_data = dict(update_data)
            # Explicit null should not mutate the existing source_site.
            if update_data.get("source_site") is None:
                update_data.pop("source_site", None)

            update_data = self._normalize_source_site_and_activation(
                {"source_site": getattr(schedule, "source_site", "jobsdb"), **update_data}
            )

            for key, value in update_data.items():
                if hasattr(schedule, key) and (value is not None or key == "category_ids"):
                    setattr(schedule, key, value)

            db.commit()
            db.refresh(schedule)
            logger.info(f"Updated schedule: {schedule.name}")
            return schedule
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating schedule {schedule_id}: {e}")
            raise

    def delete_schedule(self, db: Session, schedule_id: UUID) -> bool:
        """Delete a schedule."""
        try:
            schedule = self.get_schedule_by_id(db, schedule_id)
            if not schedule:
                return False

            db.delete(schedule)
            db.commit()
            logger.info(f"Deleted schedule: {schedule_id}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting schedule {schedule_id}: {e}")
            raise

    def toggle_schedule(
        self, db: Session, schedule_id: UUID
    ) -> Optional[ScrapeSchedule]:
        """Toggle schedule active status."""
        schedule = self.get_schedule_by_id(db, schedule_id)
        if not schedule:
            return None

        if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) not in self.SUPPORTED_SOURCE_SITES:
            schedule.is_active = False
        else:
            schedule.is_active = not schedule.is_active
        db.commit()
        db.refresh(schedule)
        return schedule

    def count_schedules(self, db: Session) -> int:
        """Count total schedules."""
        return db.query(ScrapeSchedule).count()

    # ============== Execution Operations ==============

    def get_executions(
        self, db: Session, schedule_id: UUID, limit: int = 20
    ) -> List[ScheduleExecution]:
        """Get execution history for a schedule."""
        executions = (
            db.query(ScheduleExecution)
            .filter(ScheduleExecution.schedule_id == schedule_id)
            .order_by(desc(ScheduleExecution.started_at))
            .limit(limit)
            .all()
        )
        self._attach_execution_ingest_summaries(db, executions)
        return executions

    def _resolve_execution_summary(self, metrics: dict | None) -> dict[str, int | None]:
        if not isinstance(metrics, dict):
            return {
                "jobs_settled": None,
                "jobs_dead_lettered": None,
                "listings_staged": None,
                "detail_pending": None,
                "detail_running": None,
                "detail_completed": None,
                "detail_failed": None,
                "detail_manual_action_required": None,
            }

        jobs_saved = int(metrics.get("ingest_items_seen") or 0)
        jobs_dead_lettered = int(metrics.get("ingest_dead_lettered") or 0)
        ingest_items_failed = int(metrics.get("ingest_items_failed") or 0)
        jobs_settled = int(metrics.get("ingest_items_settled") or 0)
        if jobs_settled <= 0 and (jobs_saved > 0 or jobs_dead_lettered > 0 or ingest_items_failed > 0):
            jobs_settled = jobs_saved + max(jobs_dead_lettered, ingest_items_failed)

        return {
            "jobs_settled": jobs_settled,
            "jobs_dead_lettered": jobs_dead_lettered,
            "listings_staged": int(metrics.get("listings_staged") or 0),
            "detail_pending": int(metrics.get("detail_pending") or 0),
            "detail_running": int(metrics.get("detail_running") or 0),
            "detail_completed": int(metrics.get("detail_completed") or 0),
            "detail_failed": int(metrics.get("detail_failed") or 0),
            "detail_manual_action_required": int(metrics.get("detail_manual_action_required") or 0),
        }

    def _attach_execution_ingest_summaries(
        self,
        db: Session,
        executions: List[ScheduleExecution],
    ) -> None:
        if not executions:
            return

        crawl_job_ids = [execution.crawl_job_id for execution in executions if execution.crawl_job_id]
        metrics_by_crawl_job_id = {}
        if crawl_job_ids:
            metrics_by_crawl_job_id = {
                crawl_job.id: crawl_job.metrics if isinstance(crawl_job.metrics, dict) else {}
                for crawl_job in (
                    db.query(CrawlJob)
                    .filter(CrawlJob.id.in_(crawl_job_ids))
                    .all()
                )
            }

        for execution in executions:
            summary = self._resolve_execution_summary(
                metrics_by_crawl_job_id.get(execution.crawl_job_id)
            )
            for key, value in summary.items():
                setattr(execution, key, value)

    def _attach_latest_execution_summaries(
        self,
        db: Session,
        schedules: List[ScrapeSchedule],
    ) -> None:
        if not schedules:
            return

        schedule_ids = [schedule.id for schedule in schedules]
        latest_execution_rows = (
            db.query(
                ScheduleExecution.schedule_id.label("schedule_id"),
                ScheduleExecution.status.label("status"),
                ScheduleExecution.started_at.label("started_at"),
                ScheduleExecution.completed_at.label("completed_at"),
                ScheduleExecution.jobs_scraped.label("jobs_scraped"),
                ScheduleExecution.jobs_saved.label("jobs_saved"),
                ScheduleExecution.crawl_job_id.label("crawl_job_id"),
                func.row_number().over(
                    partition_by=ScheduleExecution.schedule_id,
                    order_by=(
                        ScheduleExecution.started_at.desc(),
                        ScheduleExecution.created_at.desc(),
                    ),
                ).label("row_number"),
            )
            .filter(ScheduleExecution.schedule_id.in_(schedule_ids))
            .subquery()
        )

        latest_execution_by_schedule_id = {
            row.schedule_id: row
            for row in (
                db.query(latest_execution_rows)
                .filter(latest_execution_rows.c.row_number == 1)
                .all()
            )
        }
        crawl_job_ids = [
            row.crawl_job_id
            for row in latest_execution_by_schedule_id.values()
            if getattr(row, "crawl_job_id", None) is not None
        ]
        metrics_by_crawl_job_id = {}
        if crawl_job_ids:
            metrics_by_crawl_job_id = {
                crawl_job.id: crawl_job.metrics if isinstance(crawl_job.metrics, dict) else {}
                for crawl_job in (
                    db.query(CrawlJob)
                    .filter(CrawlJob.id.in_(crawl_job_ids))
                    .all()
                )
            }
        

        for schedule in schedules:
            latest_execution = latest_execution_by_schedule_id.get(schedule.id)
            setattr(schedule, "latest_execution_status", getattr(latest_execution, "status", None))
            setattr(schedule, "latest_execution_started_at", getattr(latest_execution, "started_at", None))
            setattr(schedule, "latest_execution_completed_at", getattr(latest_execution, "completed_at", None))
            setattr(schedule, "latest_execution_jobs_scraped", getattr(latest_execution, "jobs_scraped", None))
            setattr(schedule, "latest_execution_jobs_saved", getattr(latest_execution, "jobs_saved", None))
            summary = self._resolve_execution_summary(
                metrics_by_crawl_job_id.get(getattr(latest_execution, "crawl_job_id", None))
            )
            for key, value in summary.items():
                setattr(schedule, f"latest_execution_{key}", value)
            if getattr(schedule, "last_run_at", None) is None and getattr(latest_execution, "started_at", None) is not None:
                setattr(schedule, "last_run_at", getattr(latest_execution, "started_at"))

    def count_executions(self, db: Session, schedule_id: UUID) -> int:
        """Count total execution history rows for a schedule."""
        return (
            db.query(ScheduleExecution)
            .filter(ScheduleExecution.schedule_id == schedule_id)
            .count()
        )

    def create_execution(
        self,
        db: Session,
        schedule_id: UUID,
        status: str = "pending",
        crawl_job_id: UUID | None = None,
        auto_commit: bool = True,
    ) -> ScheduleExecution:
        """Create a new execution record."""
        execution = ScheduleExecution(
            schedule_id=schedule_id,
            crawl_job_id=crawl_job_id,
            status=status,
            started_at=utc_now(),
        )
        db.add(execution)
        if auto_commit:
            db.commit()
            db.refresh(execution)
        else:
            db.flush()
        return execution

    def update_execution(
        self, db: Session, execution_id: UUID, update_data: dict
    ) -> Optional[ScheduleExecution]:
        """Update an execution record."""
        execution = db.query(ScheduleExecution).filter(
            ScheduleExecution.id == execution_id
        ).first()
        
        if not execution:
            return None

        for key, value in update_data.items():
            if hasattr(execution, key):
                setattr(execution, key, value)

        db.commit()
        db.refresh(execution)
        return execution
