from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, text
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

    def list_with_current_revision(
        self,
        db: Session,
        *,
        source_site: str | None = None,
        lifecycle_state: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[ScrapeSchedule, AutomationRevision]], int]:
        query = (
            db.query(ScrapeSchedule, AutomationRevision)
            .join(
                AutomationRevision,
                and_(
                    AutomationRevision.automation_id == ScrapeSchedule.id,
                    AutomationRevision.revision == ScrapeSchedule.revision,
                ),
            )
            .filter(ScrapeSchedule.scope_contract.is_not(None))
        )
        if source_site is not None:
            query = query.filter(ScrapeSchedule.source_site == source_site)
        if lifecycle_state is not None:
            query = query.filter(
                ScrapeSchedule.lifecycle_state == lifecycle_state
            )
        total = int(
            query.with_entities(func.count(ScrapeSchedule.id)).scalar() or 0
        )
        rows = (
            query.order_by(
                ScrapeSchedule.updated_at.desc(),
                ScrapeSchedule.id.asc(),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows, total

    def list_for_catalog_impact(
        self,
        db: Session,
        *,
        source_site: str,
        for_update: bool = False,
    ) -> list[tuple[ScrapeSchedule, AutomationRevision]]:
        query = (
            db.query(ScrapeSchedule, AutomationRevision)
            .join(
                AutomationRevision,
                and_(
                    AutomationRevision.automation_id == ScrapeSchedule.id,
                    AutomationRevision.revision == ScrapeSchedule.revision,
                ),
            )
            .filter(
                ScrapeSchedule.scope_contract.is_not(None),
                ScrapeSchedule.source_site == source_site,
            )
            .order_by(ScrapeSchedule.id.asc())
        )
        if for_update:
            query = query.populate_existing().with_for_update()
        return query.all()

    def count_legacy_for_catalog_impact(
        self,
        db: Session,
        *,
        source_site: str,
    ) -> int:
        return int(
            db.query(func.count(ScrapeSchedule.id))
            .outerjoin(
                AutomationRevision,
                and_(
                    AutomationRevision.automation_id == ScrapeSchedule.id,
                    AutomationRevision.revision == ScrapeSchedule.revision,
                ),
            )
            .filter(
                ScrapeSchedule.source_site == source_site,
                or_(
                    ScrapeSchedule.scope_contract.is_(None),
                    AutomationRevision.id.is_(None),
                ),
            )
            .scalar()
            or 0
        )

    @staticmethod
    def lock_catalog_impact_set(db: Session) -> None:
        """Prevent versioned Automation inserts/updates during pointer change."""

        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text(
                    "LOCK TABLE scrape_schedules "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
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
