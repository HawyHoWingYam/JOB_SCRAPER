"""
Schedule Repository - Data access layer for Schedule entities.

Handles schedule and execution CRUD operations.
"""

import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
from uuid import UUID

from app.crawl_phases import resolve_crawl_phase
from app.crawl_modes import resolve_crawl_mode
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.schemas.schedule import normalize_source_site
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class ScheduleRepository:
    """Repository for Schedule database operations."""

    SUPPORTED_SOURCE_SITES = {"jobsdb", "ctgoodjobs"}

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
        return (
            db.query(ScrapeSchedule)
            .order_by(desc(ScrapeSchedule.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

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
        return (
            db.query(ScheduleExecution)
            .filter(ScheduleExecution.schedule_id == schedule_id)
            .order_by(desc(ScheduleExecution.started_at))
            .limit(limit)
            .all()
        )

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
