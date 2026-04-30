"""
Scheduler Service - Manages scheduled scraping tasks.

Uses APScheduler for cron-based job scheduling with PostgreSQL persistence.
"""

import logging
from typing import Optional
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import SessionLocal
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.schedule import normalize_source_site, validate_category_ids_for_source_site
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
        db: Session | None = None,
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
                self._execute_scrape,
                trigger=trigger,
                id=str(schedule.id),
                args=[schedule.id],
                replace_existing=True
            )
            logger.info(f"Added job: {schedule.name}")
        except Exception as e:
            logger.error(f"Failed to add job {schedule.name}: {e}")

    def _aggregate_ctgoodjobs_progress(self, scrape_service, category_ids: list[str], jobs_scraped: int) -> dict:
        """Aggregate per-category CTgoodjobs progress into execution-level metrics."""
        jobs_saved = 0
        ids_collected = 0
        jobs_classified = 0
        has_progress = False

        for category_id in category_ids:
            progress = scrape_service.get_progress(category_id) or {}
            if progress:
                has_progress = True

            jobs_saved += int(progress.get("jobs_saved", 0) or 0)
            ids_collected += int(progress.get("job_ids_collected", 0) or 0)
            jobs_classified += int(progress.get("ai_completed_items", progress.get("jobs_classified", 0)) or 0)

        if not has_progress:
            jobs_saved = jobs_scraped

        return {
            "jobs_saved": jobs_saved,
            "ids_collected": ids_collected,
            "jobs_classified": jobs_classified,
        }

    async def _execute_scrape(self, schedule_id: UUID):
        """Execute a scheduled scrape task."""
        db = SessionLocal()
        execution = None

        try:
            # Get schedule
            schedule = self.repository.get_schedule_by_id(db, schedule_id)
            if not schedule:
                logger.error(f"Schedule not found: {schedule_id}")
                return

            source_site = normalize_source_site(getattr(schedule, "source_site", "jobsdb"))
            if source_site not in self.SUPPORTED_SOURCE_SITES:
                execution = self.repository.create_execution(db, schedule_id, status="failed")
                self.repository.update_execution(
                    db,
                    execution.id,
                    {
                        "status": "failed",
                        "completed_at": utc_now(),
                        "error_message": f"Unsupported source_site for execution: {source_site}",
                    },
                )
                logger.error(f"Unsupported source_site '{source_site}' for schedule {schedule_id}")
                return

            if source_site == "ctgoodjobs":
                from app.services.ctgoodjobs_scrape_service import CtgoodjobsScrapeService

                execution = self.repository.create_execution(db, schedule_id)
                logger.info("Starting scheduled CTgoodjobs scrape: %s", getattr(schedule, "name", schedule_id))

                scrape_service = CtgoodjobsScrapeService()
                category_ids = list(schedule.category_ids or [])

                stats = await scrape_service.scrape_categories(
                    category_ids=category_ids,
                    max_pages=schedule.max_pages or 3,
                    skip_existing=True,
                )

                categories_processed = int(stats.get("categories_processed", 0) or 0)
                jobs_scraped = int(stats.get("jobs_created", 0) or 0) + int(stats.get("jobs_updated", 0) or 0)
                progress_totals = self._aggregate_ctgoodjobs_progress(scrape_service, category_ids, jobs_scraped)

                if categories_processed <= 0:
                    self.repository.update_execution(
                        db,
                        execution.id,
                        {
                            "status": "failed",
                            "completed_at": utc_now(),
                            "jobs_scraped": jobs_scraped,
                            "jobs_saved": progress_totals["jobs_saved"],
                            "ids_collected": progress_totals["ids_collected"],
                            "jobs_classified": progress_totals["jobs_classified"],
                            "error_message": "No valid CTgoodjobs categories were processed",
                        },
                    )
                    logger.error(
                        "No valid CTgoodjobs categories were processed for schedule %s",
                        schedule_id,
                    )
                    return

                self.repository.update_execution(
                    db,
                    execution.id,
                    {
                        "status": "completed",
                        "completed_at": utc_now(),
                        "jobs_scraped": jobs_scraped,
                        "jobs_saved": progress_totals["jobs_saved"],
                        "phase1_completed": True,
                        "phase2_completed": True,
                        "phase3_completed": True,
                        "phase4_completed": False,
                        "phase5_completed": False,
                        "ids_collected": progress_totals["ids_collected"],
                        "jobs_classified": progress_totals["jobs_classified"],
                    },
                )

                self.repository.update_schedule(db, schedule_id, {"last_run_at": utc_now()})
                logger.info("Completed CTgoodjobs schedule: %s, scraped %s jobs", getattr(schedule, "name", schedule_id), jobs_scraped)
                return

            # Create execution record
            execution = self.repository.create_execution(db, schedule_id)
            logger.info(f"Starting scheduled scrape: {schedule.name}")

            # Call actual scraper service
            from app.services.category_scrape_service import CategoryScrapeService
            scrape_service = CategoryScrapeService()

            # Get category IDs from schedule (or use all if not specified)
            category_ids = schedule.category_ids or []
            if not category_ids:
                from app.scraper.categories import JOBSDB_CATEGORIES
                category_ids = list(JOBSDB_CATEGORIES.keys())

            # Execute scraping
            stats = await scrape_service.scrape_categories(
                category_ids=category_ids,
                max_pages=schedule.max_pages or 3,
                skip_existing=True,
            )

            # Get final progress data for phase tracking
            progress = scrape_service.get_progress(category_ids[0]) if category_ids else {}
            jobs_scraped = stats.get("jobs_created", 0) + stats.get("jobs_updated", 0)
            jobs_saved = progress.get("jobs_saved", jobs_scraped)
            progress_status = progress.get("status")
            ai_run_status = stats.get("ai_run_status")
            ai_run_started = bool(stats.get("ai_run_id") or progress.get("ai_run_id"))
            ai_completed_count = progress.get("ai_completed_items", progress.get("jobs_classified", 0))

            execution_status = "completed"
            phase5_completed = False
            if progress_status == "ai_running" or ai_run_status == "running":
                execution_status = "ai_running"
            elif progress_status == "completed_with_ai_failures" or ai_run_status in {"completed_with_failures", "failed"}:
                execution_status = "completed_with_ai_failures"
                phase5_completed = ai_run_started
            elif progress_status == "completed":
                execution_status = "completed"
                phase5_completed = ai_run_started

            # Update execution as completed
            self.repository.update_execution(db, execution.id, {
                "status": execution_status,
                "completed_at": utc_now(),
                "jobs_scraped": jobs_scraped,
                "jobs_saved": jobs_saved,
                "phase1_completed": True,
                "phase2_completed": True,
                "phase3_completed": True,
                "phase4_completed": ai_run_started,
                "phase5_completed": phase5_completed,
                "ids_collected": progress.get("job_ids_collected", 0),
                "jobs_classified": ai_completed_count,
            })

            # Update schedule last_run_at
            self.repository.update_schedule(db, schedule_id, {
                "last_run_at": utc_now()
            })

            logger.info(f"Completed: {schedule.name}, scraped {jobs_scraped} jobs")

        except Exception as e:
            logger.error(f"Scrape failed for {schedule_id}: {e}")
            if execution:
                self.repository.update_execution(db, execution.id, {
                    "status": "failed",
                    "completed_at": utc_now(),
                    "error_message": str(e)
                })
        finally:
            db.close()

    # ============== Public Methods ==============

    def add_schedule(self, schedule: ScrapeSchedule):
        """Add a new schedule to the scheduler."""
        if normalize_source_site(getattr(schedule, "source_site", "jobsdb")) not in self.SUPPORTED_SOURCE_SITES:
            return
        if schedule.is_active:
            self._add_job(schedule)

    def remove_schedule(self, schedule_id: UUID):
        """Remove a schedule from the scheduler."""
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
        await self._execute_scrape(schedule_id)

    def shutdown(self):
        """Shutdown the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Scheduler shutdown")
