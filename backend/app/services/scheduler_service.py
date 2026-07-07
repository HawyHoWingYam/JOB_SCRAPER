"""
Scheduler Service - Manages scheduled scraping tasks.

Uses APScheduler for cron-based job scheduling with PostgreSQL persistence.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import SessionLocal
from app.models.schedule import ScrapeSchedule, SchedulerRuntimeHeartbeat
from app.repositories.schedule_repository import ScheduleRepository
from app.services.crawl_request_validation import normalize_source_site, validate_category_ids_for_source_site
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_category_registry import get_source_category_registry
from app.services.source_catalog import is_supported_source_site
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


def _normalize_next_run_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


async def run_scheduled_crawl_job(schedule_id: str, *, trigger_type: str = "schedule"):
    """Serializable APScheduler entrypoint that dispatches a persisted schedule."""
    return await SchedulerService.get_instance()._dispatch_schedule(UUID(str(schedule_id)), trigger_type=trigger_type)


class SchedulerService:
    """Service for managing scheduled scraping tasks."""

    _instance: Optional["SchedulerService"] = None

    def __init__(self, *, owner: str = "scheduler-worker", worker_name: str | None = None):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.repository = ScheduleRepository()
        self.dispatch_service = CrawlJobDispatchService()
        self._initialized = False
        self.owner = owner
        self.worker_name = worker_name or owner
        self._reconcile_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._started_at = utc_now()
        self._last_reconcile_at = None
        self._last_error: str | None = None
        self._active_schedule_count = 0
        self._registered_job_count = 0

    @classmethod
    def get_instance(
        cls,
        *,
        owner: str = "scheduler-worker",
        worker_name: str | None = None,
    ) -> "SchedulerService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(owner=owner, worker_name=worker_name)
        else:
            cls._instance.owner = owner or cls._instance.owner
            if worker_name:
                cls._instance.worker_name = worker_name
        return cls._instance

    async def initialize(self):
        """Initialize the scheduler and start reconcile/heartbeat loops."""
        if self._initialized and self.scheduler and getattr(self.scheduler, "running", False):
            return

        logger.info(
            "Initializing scheduler service (owner=%s, worker_name=%s)...",
            self.owner,
            self.worker_name,
        )

        if self.scheduler is None:
            jobstores = {
                "default": SQLAlchemyJobStore(url=settings.database_url)
            }
            self.scheduler = AsyncIOScheduler(
                jobstores=jobstores,
                timezone="UTC",
            )

        self.scheduler.start()
        self._initialized = True
        self._started_at = utc_now()

        await self.reconcile_schedules()
        self._write_runtime_heartbeat(status="running")

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self._reconcile_task is None or self._reconcile_task.done():
            self._reconcile_task = asyncio.create_task(self._reconcile_loop())

        logger.info("Scheduler service initialized")

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(settings.scheduler_heartbeat_interval_seconds)
                self._write_runtime_heartbeat(status="running")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler heartbeat loop failed")
            self._last_error = "scheduler_heartbeat_loop_failed"
            self._write_runtime_heartbeat(status="degraded", last_error=self._last_error)

    async def _reconcile_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(settings.scheduler_reconcile_interval_seconds)
                await self.reconcile_schedules()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler reconcile loop failed")
            self._last_error = "scheduler_reconcile_loop_failed"
            self._write_runtime_heartbeat(status="degraded", last_error=self._last_error)

    async def _load_active_schedules(self):
        """Load all active schedules from database without live registry dependency."""
        db = SessionLocal()
        try:
            schedules = self.repository.get_active_schedules(db)
            for schedule in schedules:
                if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) == "ctgoodjobs":
                    is_valid, validation_error, should_deactivate = self._validate_ctgoodjobs_schedule_shape(
                        schedule
                    )
                    if not is_valid:
                        logger.info(
                            "Skipping scheduler registration for invalid CTgoodjobs schedule %s: %s",
                            getattr(schedule, "id", None),
                            validation_error,
                        )
                        if should_deactivate and getattr(schedule, "is_active", False):
                            self.repository.update_schedule(db, schedule.id, {"is_active": False})
                        continue

                    self._add_job(schedule, db=db, ctgoodjobs_validated=True)
                    continue

                self._add_job(schedule, db=db)
            db.commit()
            logger.info("Loaded %s active schedules", len(schedules))
        finally:
            db.close()

    def _validate_ctgoodjobs_schedule_shape(
        self, schedule: ScrapeSchedule
    ) -> tuple[bool, str | None, bool]:
        """Validate persisted CTgoodjobs schedules without any network dependency."""
        category_ids = getattr(schedule, "category_ids", None)

        try:
            validate_category_ids_for_source_site("ctgoodjobs", category_ids)
        except ValueError as exc:
            return False, str(exc), True

        return True, None, False

    def _validate_ctgoodjobs_schedule(self, schedule: ScrapeSchedule) -> tuple[bool, str | None, bool]:
        """Validate persisted CTgoodjobs schedules for scheduler use.

        Returns `(is_valid, error_message, should_deactivate)`.
        """
        is_valid, validation_error, should_deactivate = self._validate_ctgoodjobs_schedule_shape(schedule)
        if not is_valid:
            return is_valid, validation_error, should_deactivate

        try:
            categories = get_source_category_registry().list_categories(source_site="ctgoodjobs")
        except Exception as exc:
            logger.error(
                "Skipping CTgoodjobs schedule %s because registry validation failed: %s",
                getattr(schedule, "id", None),
                exc,
            )
            return False, "CTgoodjobs category registry unavailable", False

        supported_ids = {str(category["id"]) for category in categories}
        category_ids = getattr(schedule, "category_ids", None)
        unknown_ids = sorted(
            {
                str(category_id)
                for category_id in (category_ids or [])
                if str(category_id) not in supported_ids
            }
        )
        if unknown_ids:
            return False, f"Unknown CTgoodjobs category_ids: {', '.join(unknown_ids)}", True

        return True, None, False

    def _add_job(
        self,
        schedule: ScrapeSchedule,
        db=None,
        *,
        ctgoodjobs_validated: bool = False,
    ) -> bool:
        """Add or replace a job in the scheduler."""
        if self.scheduler is None:
            return False

        source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        if not is_supported_source_site(source_site):
            logger.info(
                "Skipping scheduler registration for unsupported source_site '%s' (schedule_id=%s)",
                source_site,
                getattr(schedule, "id", None),
            )
            return False

        if source_site == "ctgoodjobs" and not ctgoodjobs_validated:
            is_valid, validation_error, should_deactivate = self._validate_ctgoodjobs_schedule(schedule)
            if not is_valid:
                logger.info(
                    "Skipping scheduler registration for invalid CTgoodjobs schedule %s: %s",
                    getattr(schedule, "id", None),
                    validation_error,
                )
                if should_deactivate and db is not None and getattr(schedule, "is_active", False):
                    self.repository.update_schedule(db, schedule.id, {"is_active": False})
                return False

        try:
            trigger = CronTrigger.from_crontab(
                schedule.cron_expression,
                timezone=ZoneInfo(getattr(schedule, "timezone", None) or "Asia/Hong_Kong"),
            )
            job = self.scheduler.add_job(
                run_scheduled_crawl_job,
                trigger=trigger,
                id=str(schedule.id),
                args=[str(schedule.id)],
                replace_existing=True,
            )
            if db is not None:
                schedule.next_run_at = _normalize_next_run_at(getattr(job, "next_run_time", None))
                db.add(schedule)
            logger.info("Registered scheduler job: %s", schedule.name)
            return True
        except Exception:
            logger.exception("Failed to add job %s", schedule.name)
            return False

    async def reconcile_schedules(self) -> None:
        """Rebuild APScheduler state from `scrape_schedules`."""
        if self.scheduler is None:
            return

        db = SessionLocal()
        reconcile_started_at = utc_now()
        try:
            active_schedules = self.repository.get_active_schedules(db)
            active_job_ids: set[str] = set()

            for schedule in active_schedules:
                source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
                if source_site == "ctgoodjobs":
                    is_valid, validation_error, should_deactivate = self._validate_ctgoodjobs_schedule_shape(schedule)
                    if not is_valid:
                        logger.info(
                            "Skipping scheduler registration for invalid CTgoodjobs schedule %s: %s",
                            getattr(schedule, "id", None),
                            validation_error,
                        )
                        if should_deactivate and getattr(schedule, "is_active", False):
                            self.repository.update_schedule(db, schedule.id, {"is_active": False})
                        schedule.next_run_at = None
                        db.add(schedule)
                        continue
                    added = self._add_job(schedule, db=db, ctgoodjobs_validated=True)
                else:
                    added = self._add_job(schedule, db=db)

                if added:
                    active_job_ids.add(str(schedule.id))
                else:
                    schedule.next_run_at = None
                    db.add(schedule)

            for job in list(self.scheduler.get_jobs()):
                if str(job.id) not in active_job_ids:
                    self.scheduler.remove_job(job.id)
                    try:
                        stale_schedule = self.repository.get_schedule_by_id(db, UUID(str(job.id)))
                    except ValueError:
                        stale_schedule = None
                    if stale_schedule is not None:
                        stale_schedule.next_run_at = None
                        db.add(stale_schedule)
                    logger.info("Removed stale scheduler job: %s", job.id)

            db.commit()
            self._active_schedule_count = len(active_job_ids)
            self._registered_job_count = len(self.scheduler.get_jobs())
            self._last_reconcile_at = reconcile_started_at
            self._last_error = None
            self._write_runtime_heartbeat(status="running")
        except Exception as exc:
            self._last_reconcile_at = reconcile_started_at
            self._last_error = str(exc)
            self._write_runtime_heartbeat(status="degraded", last_error=self._last_error)
            raise
        finally:
            db.close()

    def _write_runtime_heartbeat(self, *, status: str, last_error: str | None = None) -> None:
        db = SessionLocal()
        try:
            heartbeat = (
                db.query(SchedulerRuntimeHeartbeat)
                .filter(SchedulerRuntimeHeartbeat.id == 1)
                .one_or_none()
            )
            now = utc_now()
            if heartbeat is None:
                heartbeat = SchedulerRuntimeHeartbeat(
                    id=1,
                    owner=self.owner,
                    worker_name=self.worker_name,
                    started_at=self._started_at,
                    last_heartbeat_at=now,
                    status=status,
                    active_schedule_count=self._active_schedule_count,
                    registered_job_count=self._registered_job_count,
                    last_reconcile_at=self._last_reconcile_at,
                    last_error=last_error or self._last_error,
                )
                db.add(heartbeat)
            else:
                heartbeat.owner = self.owner
                heartbeat.worker_name = self.worker_name
                heartbeat.started_at = self._started_at
                heartbeat.last_heartbeat_at = now
                heartbeat.status = status
                heartbeat.active_schedule_count = self._active_schedule_count
                heartbeat.registered_job_count = self._registered_job_count
                heartbeat.last_reconcile_at = self._last_reconcile_at
                heartbeat.last_error = last_error or self._last_error

            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist scheduler runtime heartbeat")
        finally:
            db.close()

    async def _dispatch_schedule(self, schedule_id: UUID, *, trigger_type: str = "schedule"):
        """Dispatch a scheduled crawl request into the durable crawl job control plane."""
        db = SessionLocal()
        try:
            schedule = self.repository.get_schedule_by_id(db, schedule_id)
            if not schedule:
                logger.error("Schedule not found: %s", schedule_id)
                return None

            source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
            if not is_supported_source_site(source_site):
                logger.error("Unsupported source_site '%s' for schedule %s", source_site, schedule_id)
                return None

            dispatch_result = self.dispatch_service.dispatch_schedule_crawl_job(
                db,
                schedule=schedule,
                requested_by="scheduler-worker" if trigger_type == "schedule" else "api",
                trigger_type=trigger_type,
            )
            logger.info(
                "Queued crawl job %s for schedule %s via %s trigger",
                dispatch_result.crawl_job.id,
                schedule_id,
                trigger_type,
            )
            return dispatch_result.crawl_job
        except Exception:
            db.rollback()
            logger.exception("Failed to dispatch crawl job for schedule %s", schedule_id)
            return None
        finally:
            db.close()

    async def _execute_scrape(self, schedule_id: UUID):
        """Backward-compatible alias for schedule dispatch during the worker cutover."""
        return await self._dispatch_schedule(schedule_id)

    # ============== Public Methods ==============

    def add_schedule(self, schedule: ScrapeSchedule):
        """Add a new schedule to the scheduler."""
        if not is_supported_source_site(normalize_source_site(getattr(schedule, "source_site", "jobsdb"))):
            return
        if schedule.is_active:
            self._add_job(schedule)

    def remove_schedule(self, schedule_id: UUID):
        """Remove a schedule from the scheduler."""
        if self.scheduler is None:
            return
        job_id = str(schedule_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("Removed job: %s", schedule_id)

    def update_schedule(self, schedule: ScrapeSchedule):
        """Update a schedule in the scheduler."""
        self.remove_schedule(schedule.id)
        if not is_supported_source_site(normalize_source_site(getattr(schedule, "source_site", "jobsdb"))):
            return
        if schedule.is_active:
            self._add_job(schedule)

    async def run_now(self, schedule_id: UUID):
        """Run a schedule immediately."""
        return await self._dispatch_schedule(schedule_id, trigger_type="manual")

    def shutdown(self):
        """Shutdown the scheduler."""
        for task in (self._heartbeat_task, self._reconcile_task):
            if task is not None and not task.done():
                task.cancel()
        self._heartbeat_task = None
        self._reconcile_task = None

        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Scheduler shutdown")

        self._write_runtime_heartbeat(status="stopped")
        self._initialized = False
