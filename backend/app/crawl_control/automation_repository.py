from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.crawl_control.automation_contracts import AutomationDeleteImpactV1
from app.models.crawl_job import CrawlJob
from app.models.schedule import (
    AutomationDeleteReview,
    AutomationRevision,
    ScheduleExecution,
    ScrapeSchedule,
)


class AutomationRepository:
    """Locking persistence seam for versioned Automation state."""

    def get(
        self,
        db: Session,
        automation_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScrapeSchedule | None:
        query = db.query(ScrapeSchedule).filter(
            ScrapeSchedule.id == automation_id
        )
        if for_update:
            query = query.populate_existing().with_for_update()
        return query.one_or_none()

    def get_revision(
        self,
        db: Session,
        *,
        automation_id: UUID,
        revision: int,
    ) -> AutomationRevision | None:
        return (
            db.query(AutomationRevision)
            .filter(
                AutomationRevision.automation_id == automation_id,
                AutomationRevision.revision == revision,
            )
            .one_or_none()
        )

    def append_revision(
        self,
        db: Session,
        *,
        automation_id: UUID,
        revision: int,
        snapshot: dict,
        snapshot_fingerprint: str,
        operation: str,
        actor: str,
    ) -> AutomationRevision:
        row = AutomationRevision(
            automation_id=automation_id,
            revision=revision,
            snapshot=dict(snapshot),
            snapshot_fingerprint=snapshot_fingerprint,
            operation=operation,
            actor=actor,
        )
        db.add(row)
        db.flush()
        return row

    def delete_impact(
        self,
        db: Session,
        automation: ScrapeSchedule,
    ) -> AutomationDeleteImpactV1:
        return AutomationDeleteImpactV1(
            automation_id=automation.id,
            expected_revision=automation.revision,
            automation_revision_count=(
                db.query(AutomationRevision)
                .filter(AutomationRevision.automation_id == automation.id)
                .count()
            ),
            schedule_execution_count=(
                db.query(ScheduleExecution)
                .filter(ScheduleExecution.schedule_id == automation.id)
                .count()
            ),
            crawl_job_count=(
                db.query(CrawlJob)
                .filter(CrawlJob.schedule_id == automation.id)
                .count()
            ),
            removed_records=("automation", "automation_revisions"),
            preserved_records=(
                "schedule_executions",
                "crawl_jobs",
                "run_history",
            ),
        )

    def get_delete_review_for_update(
        self,
        db: Session,
        *,
        token_hash: str,
    ) -> AutomationDeleteReview | None:
        return (
            db.query(AutomationDeleteReview)
            .filter(AutomationDeleteReview.token_hash == token_hash)
            .with_for_update()
            .one_or_none()
        )
