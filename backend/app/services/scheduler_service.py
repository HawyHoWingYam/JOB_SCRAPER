"""
Scheduler Service - Manages scheduled scraping tasks.

Uses APScheduler for cron-based job scheduling with PostgreSQL persistence.
"""

import logging
from typing import Optional
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import SessionLocal
from app.models.schedule import ScrapeSchedule
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.schedule import normalize_source_site, validate_category_ids_for_source_site
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_category_registry import get_source_category_registry
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing scheduled scraping tasks."""

    _instance: Optional["SchedulerService"] = None
    SUPPORTED_SOURCE_SITES = {"jobsdb", "ctgoodjobs"}

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.repository = ScheduleRepository()
        self.dispatch_service = CrawlJobDispatchService()
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "SchedulerService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self):
        """Initialize the scheduler and load active schedules."""
        if self._initialized:
            return

        logger.info("Initializing scheduler service...")

        # Create scheduler with job store
        jobstores = {
            "default": SQLAlchemyJobStore(url=settings.database_url)
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone="Asia/Hong_Kong"
        )

        # Start scheduler
        self.scheduler.start()
        self._initialized = True

        # Load active schedules from database
        await self._load_active_schedules()

        logger.info("Scheduler service initialized")

    async def _load_active_schedules(self):
        """Load all active schedules from database."""
        db = SessionLocal()
        try:
            schedules = self.repository.get_active_schedules(db)
            for schedule in schedules:
                if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) == "ctgoodjobs":
                    is_valid, validation_error, should_deactivate = await run_in_threadpool(
                        self._validate_ctgoodjobs_schedule,
                        schedule,
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

                        # Startup should not permanently unschedule CTgoodjobs rows only because
                        # registry validation could not be performed right now.
                        self._add_job(schedule, db=db, ctgoodjobs_validated=True)
                        continue

                    self._add_job(schedule, db=db, ctgoodjobs_validated=True)
                    continue

                self._add_job(schedule, db=db)
            logger.info(f"Loaded {len(schedules)} active schedules")
        finally:
            db.close()

    def _validate_ctgoodjobs_schedule(self, schedule: ScrapeSchedule) -> tuple[bool, str | None, bool]:
        """Validate persisted CTgoodjobs schedules for scheduler use.

        Returns `(is_valid, error_message, should_deactivate)`.
        """
        category_ids = getattr(schedule, "category_ids", None)

        try:
            validate_category_ids_for_source_site("ctgoodjobs", category_ids)
        except ValueError as exc:
            return False, str(exc), True

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
    ):
        """Add a job to the scheduler."""
        source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
        if source_site not in self.SUPPORTED_SOURCE_SITES:
            logger.info(
                "Skipping scheduler registration for unsupported source_site '%s' (schedule_id=%s)",
                source_site,
                getattr(schedule, "id", None),
            )
            return

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
                return

        try:
            trigger = CronTrigger.from_crontab(schedule.cron_expression)
            self.scheduler.add_job(
                self._dispatch_schedule,
                trigger=trigger,
                id=str(schedule.id),
                args=[schedule.id],
                replace_existing=True
            )
            logger.info(f"Added job: {schedule.name}")
        except Exception as e:
            logger.error(f"Failed to add job {schedule.name}: {e}")

    async def _dispatch_schedule(self, schedule_id: UUID, *, trigger_type: str = "schedule"):
        """Dispatch a scheduled crawl request into the durable crawl job control plane."""
        db = SessionLocal()
        try:
            schedule = self.repository.get_schedule_by_id(db, schedule_id)
            if not schedule:
                logger.error(f"Schedule not found: {schedule_id}")
                return None

            source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
            if source_site not in self.SUPPORTED_SOURCE_SITES:
                logger.error(f"Unsupported source_site '{source_site}' for schedule {schedule_id}")
                return None

            schedule.last_run_at = utc_now()
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
        if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) not in self.SUPPORTED_SOURCE_SITES:
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
            logger.info(f"Removed job: {schedule_id}")

    def update_schedule(self, schedule: ScrapeSchedule):
        """Update a schedule in the scheduler."""
        self.remove_schedule(schedule.id)
        if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) not in self.SUPPORTED_SOURCE_SITES:
            return
        if schedule.is_active:
            self._add_job(schedule)

    async def run_now(self, schedule_id: UUID):
        """Run a schedule immediately."""
        return await self._dispatch_schedule(schedule_id, trigger_type="manual")

    def shutdown(self):
        """Shutdown the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Scheduler shutdown")
