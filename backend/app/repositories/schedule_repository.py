"""Persistence helpers for current Automations and their executions."""

from typing import Optional
from sqlalchemy.orm import Session
from uuid import UUID

from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.utils.time import utc_now


class ScheduleRepository:
    """Repository operations shared by current Automation services."""

    def get_active_schedules(self, db: Session) -> list[ScrapeSchedule]:
        """Get all active schedules."""
        return (
            db.query(ScrapeSchedule)
            .filter(ScrapeSchedule.lifecycle_state == "active")
            .all()
        )

    def get_schedule_by_id(
        self, db: Session, schedule_id: UUID
    ) -> Optional[ScrapeSchedule]:
        """Get schedule by ID."""
        return db.query(ScrapeSchedule).filter(ScrapeSchedule.id == schedule_id).first()

    def get_schedule_by_id_for_update(
        self, db: Session, schedule_id: UUID
    ) -> Optional[ScrapeSchedule]:
        """Lock one schedule so lifecycle validation fences dispatch."""
        return (
            db.query(ScrapeSchedule)
            .filter(ScrapeSchedule.id == schedule_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    def create_execution(
        self,
        db: Session,
        schedule_id: UUID,
        status: str = "pending",
        crawl_job_id: UUID | None = None,
        automation_id_snapshot: UUID | None = None,
        automation_snapshot: dict | None = None,
        dispatch_plan_id: UUID | None = None,
        dispatch_plan_fingerprint: str | None = None,
        auto_commit: bool = True,
    ) -> ScheduleExecution:
        """Create a new execution record."""
        if (dispatch_plan_id is None) != (dispatch_plan_fingerprint is None):
            raise ValueError(
                "Schedule Execution Dispatch Plan ID and fingerprint "
                "must be supplied together"
            )
        if (
            dispatch_plan_fingerprint is not None
            and len(dispatch_plan_fingerprint) != 64
        ):
            raise ValueError(
                "Schedule Execution Dispatch Plan fingerprint must be SHA-256"
            )
        execution = ScheduleExecution(
            schedule_id=schedule_id,
            crawl_job_id=crawl_job_id,
            automation_id_snapshot=automation_id_snapshot,
            automation_snapshot=(
                dict(automation_snapshot)
                if automation_snapshot is not None
                else None
            ),
            dispatch_plan_id=dispatch_plan_id,
            dispatch_plan_fingerprint=dispatch_plan_fingerprint,
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
