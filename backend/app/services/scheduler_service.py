"""
Scheduler Service - Manages scheduled scraping tasks.

APScheduler is a rebuildable in-memory timer over persisted `scrape_schedules`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import SessionLocal
from app.models.schedule import ScrapeSchedule, SchedulerRuntimeHeartbeat
from app.repositories.schedule_repository import ScheduleRepository
from app.services.crawl_request_validation import normalize_source_site
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_sites import is_supported_source_site
from app.utils.time import utc_now

logger = logging.getLogger(__name__)
JEV_MAINTENANCE_JOB_ID = "system:jev-skill-maintenance"


def _build_runtime_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone="UTC")


def _normalize_next_run_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def run_scheduled_crawl_job(
    schedule_id: str,
    *,
    trigger_type: str = "schedule",
):
    """Serializable APScheduler entrypoint that dispatches a persisted schedule."""
    return await SchedulerService.get_instance()._dispatch_schedule(
        UUID(str(schedule_id)),
        trigger_type=trigger_type,
    )


async def run_scheduled_jev_skill_maintenance():
    """Serializable APScheduler entrypoint for durable Skill maintenance."""
    return await SchedulerService.get_instance()._run_jev_skill_maintenance()


class SchedulerService:
    """Service for managing scheduled scraping tasks."""

    _instance: Optional["SchedulerService"] = None

    def __init__(
        self, *, owner: str = "scheduler-worker", worker_name: str | None = None
    ):
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
        if (
            self._initialized
            and self.scheduler
            and getattr(self.scheduler, "running", False)
        ):
            return

        logger.info(
            "Initializing scheduler service (owner=%s, worker_name=%s)...",
            self.owner,
            self.worker_name,
        )

        if self.scheduler is None:
            self.scheduler = _build_runtime_scheduler()

        self.scheduler.start()
        self._initialized = True
        self._started_at = utc_now()

        await self.reconcile_schedules()
        self._register_jev_maintenance_job()
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
            self._write_runtime_heartbeat(
                status="degraded", last_error=self._last_error
            )

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
            self._write_runtime_heartbeat(
                status="degraded", last_error=self._last_error
            )

    async def _load_active_schedules(self):
        """Load all active schedules from database without live registry dependency."""
        db = SessionLocal()
        try:
            schedules = self.repository.get_active_schedules(db)
            for schedule in schedules:
                self._add_job(schedule, db=db)
            db.commit()
            logger.info("Loaded %s active schedules", len(schedules))
        finally:
            db.close()

    def _add_job(
        self,
        schedule: ScrapeSchedule,
        db=None,
    ) -> bool:
        """Add or replace a job in the scheduler."""
        if self.scheduler is None:
            return False
        if getattr(schedule, "lifecycle_state", "paused") != "active":
            return False

        source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        if not is_supported_source_site(source_site):
            logger.info(
                "Skipping scheduler registration for unsupported source_site '%s' (schedule_id=%s)",
                source_site,
                getattr(schedule, "id", None),
            )
            return False

        try:
            trigger = CronTrigger.from_crontab(
                schedule.cron_expression,
                timezone=ZoneInfo(
                    getattr(schedule, "timezone", None) or "Asia/Hong_Kong"
                ),
            )
            job = self.scheduler.add_job(
                run_scheduled_crawl_job,
                trigger=trigger,
                id=str(schedule.id),
                args=[str(schedule.id)],
                replace_existing=True,
            )
            if db is not None:
                schedule.next_run_at = _normalize_next_run_at(
                    getattr(job, "next_run_time", None)
                )
                db.add(schedule)
            logger.info("Registered scheduler job: %s", schedule.name)
            return True
        except Exception:
            logger.exception("Failed to add job %s", schedule.name)
            return False

    def _register_jev_maintenance_job(self) -> None:
        if self.scheduler is None:
            return
        self.scheduler.add_job(
            run_scheduled_jev_skill_maintenance,
            trigger="interval",
            seconds=settings.jev_maintenance_poll_interval_seconds,
            id=JEV_MAINTENANCE_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=utc_now(),
        )

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
                added = self._add_job(schedule, db=db)

                if added:
                    active_job_ids.add(str(schedule.id))
                else:
                    schedule.next_run_at = None
                    db.add(schedule)

            for job in list(self.scheduler.get_jobs()):
                if str(job.id) == JEV_MAINTENANCE_JOB_ID:
                    continue
                if str(job.id) not in active_job_ids:
                    self.scheduler.remove_job(job.id)
                    try:
                        stale_schedule = self.repository.get_schedule_by_id(
                            db, UUID(str(job.id))
                        )
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
            self._write_runtime_heartbeat(
                status="degraded", last_error=self._last_error
            )
            raise
        finally:
            db.close()

    async def _run_jev_skill_maintenance(self):
        """Resume pending maintenance or perform one free scheduled eligibility check."""
        from app.services.jev_evaluator_factory import build_jev_evaluator
        from app.services.jev_run_service import JevRunConfigurationError, JevRunService
        from app.services.jev_skill_maintenance import JevSkillMaintenanceService

        db = SessionLocal()
        evaluator = None
        batch = None
        try:
            service = JevSkillMaintenanceService(db)
            batch = service.pending()
            if batch is None:
                eligibility, batch = service.start(trigger="scheduled")
                db.commit()
                if batch is None:
                    logger.debug(
                        "Jev Skill maintenance not dispatched: %s",
                        eligibility.reason,
                    )
                    return None
            else:
                db.commit()
            run = JevRunService(db).get(batch.jev_run_id)
            evaluator = build_jev_evaluator(db, run)
            batch = await service.execute(batch.id, evaluator=evaluator)
            db.commit()
            return batch
        except JevRunConfigurationError:
            db.rollback()
            if batch is not None:
                service = JevSkillMaintenanceService(db)
                service.mark_unavailable(
                    batch.id,
                    error_code="configuration_error",
                )
                db.commit()
            logger.exception("Scheduled Jev Skill maintenance configuration failed")
            return None
        except Exception:
            db.rollback()
            logger.exception("Scheduled Jev Skill maintenance failed")
            return None
        finally:
            close = getattr(evaluator, "aclose", None)
            if close is not None:
                await close()
            db.close()

    def _write_runtime_heartbeat(
        self, *, status: str, last_error: str | None = None
    ) -> None:
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

    async def _dispatch_schedule(
        self,
        schedule_id: UUID,
        *,
        trigger_type: str = "schedule",
    ):
        """Dispatch a scheduled crawl request into the durable crawl job control plane."""
        db = SessionLocal()
        request_reconcile = False
        try:
            schedule = self.repository.get_schedule_by_id_for_update(db, schedule_id)
            if not schedule:
                logger.error("Schedule not found: %s", schedule_id)
                request_reconcile = trigger_type == "schedule"
                return None

            if trigger_type == "schedule" and schedule.lifecycle_state != "active":
                logger.info(
                    "Skipping inactive scheduler callback schedule_id=%s lifecycle=%s",
                    schedule_id,
                    schedule.lifecycle_state,
                )
                request_reconcile = True
                return None
            if trigger_type != "schedule" and schedule.lifecycle_state in {
                "archived",
                "scope_review_required",
            }:
                logger.info(
                    "Skipping manual Automation dispatch schedule_id=%s lifecycle=%s",
                    schedule_id,
                    schedule.lifecycle_state,
                )
                return None
            # Paused blocks cron dispatch only. An explicit manual "Run saved
            # configuration" remains allowed; archive/review states do not.

            source_site = normalize_source_site(
                getattr(schedule, "source_site", "jobsdb")
            )
            if not is_supported_source_site(source_site):
                logger.error(
                    "Unsupported source_site '%s' for schedule %s",
                    source_site,
                    schedule_id,
                )
                return None

            dispatch_result = self.dispatch_service.dispatch_schedule_crawl_job(
                db,
                schedule=schedule,
                requested_by="scheduler-worker"
                if trigger_type == "schedule"
                else "api",
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
            logger.exception(
                "Failed to dispatch crawl job for schedule %s", schedule_id
            )
            return None
        finally:
            db.close()
            if request_reconcile:
                self._request_reconcile()

    def _request_reconcile(self) -> None:
        if not self._initialized or self.scheduler is None:
            return
        try:
            asyncio.create_task(self.reconcile_schedules())
        except RuntimeError:
            return

    async def _execute_scrape(self, schedule_id: UUID):
        """Backward-compatible alias for schedule dispatch during the worker cutover."""
        return await self._dispatch_schedule(
            schedule_id,
            trigger_type="schedule",
        )

    # ============== Public Methods ==============

    def add_schedule(self, schedule: ScrapeSchedule):
        """Add a new schedule to the scheduler."""
        if not is_supported_source_site(
            normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        ):
            return
        if schedule.lifecycle_state == "active":
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
        if not is_supported_source_site(
            normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        ):
            return
        if schedule.lifecycle_state == "active":
            self._add_job(schedule)

    async def run_now(self, schedule_id: UUID):
        """Run a schedule immediately."""
        return await self._dispatch_schedule(
            schedule_id,
            trigger_type="manual",
        )

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
