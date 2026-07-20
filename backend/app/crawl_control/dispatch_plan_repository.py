from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanContentV1,
    DispatchPlanReadinessV1,
    DispatchPlanTargetV1,
)
from app.models.crawl_dispatch_plan import (
    CrawlDispatchPlan,
    CrawlDispatchPlanTarget,
    CrawlDispatchPlanTargetRow,
)


class DispatchPlanRepository:
    """Locking persistence seam for immutable Dispatch Plan snapshots."""

    def add_prepared(
        self,
        db: Session,
        *,
        plan_id: UUID,
        content: DispatchPlanContentV1,
        readiness: DispatchPlanReadinessV1,
        targets: tuple[DispatchPlanTargetV1, ...],
        plan_fingerprint: str,
        confirmation_required: bool,
        confirmation_token_hash: str | None,
        prepared_by: str,
        prepared_at: datetime,
        expires_at: datetime,
    ) -> CrawlDispatchPlan:
        plan = CrawlDispatchPlan(
            id=plan_id,
            state="prepared",
            source_site=content.source_site,
            crawl_phase=content.crawl_phase,
            trigger_kind=content.trigger_kind,
            automation_id=content.automation_id,
            automation_id_snapshot=content.automation_id,
            expected_automation_revision=content.expected_automation_revision,
            catalog_revision_id=content.catalog_revision_id,
            authored_scope=content.authored_scope.model_dump(mode="json"),
            resolved_scope=content.resolved_scope.model_dump(mode="json"),
            listing_settings=(
                content.listing_settings.model_dump(mode="json")
                if content.listing_settings is not None
                else None
            ),
            detail_settings=(
                content.detail_settings.model_dump(mode="json")
                if content.detail_settings is not None
                else None
            ),
            readiness=readiness.model_dump(mode="json"),
            detail_target_count=len(targets),
            plan_fingerprint=plan_fingerprint,
            confirmation_required=confirmation_required,
            confirmation_token_hash=confirmation_token_hash,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            expires_at=expires_at,
            targets=[self._target_model(target) for target in targets],
        )
        db.add(plan)
        db.flush()
        return plan

    def get(
        self,
        db: Session,
        plan_id: UUID,
        *,
        for_update: bool = False,
    ) -> CrawlDispatchPlan | None:
        query = (
            db.query(CrawlDispatchPlan)
            .options(
                selectinload(CrawlDispatchPlan.targets).selectinload(
                    CrawlDispatchPlanTarget.rows
                )
            )
            .filter(CrawlDispatchPlan.id == plan_id)
        )
        if for_update:
            query = query.populate_existing().with_for_update()
        return query.one_or_none()

    def get_by_crawl_job_id(
        self,
        db: Session,
        crawl_job_id: UUID,
    ) -> CrawlDispatchPlan | None:
        return (
            db.query(CrawlDispatchPlan)
            .options(
                selectinload(CrawlDispatchPlan.targets).selectinload(
                    CrawlDispatchPlanTarget.rows
                )
            )
            .filter(CrawlDispatchPlan.crawl_job_id == crawl_job_id)
            .one_or_none()
        )

    def mark_consumed(
        self,
        plan: CrawlDispatchPlan,
        *,
        crawl_job_id: UUID,
        consumed_at: datetime,
    ) -> None:
        plan.state = "consumed"
        plan.crawl_job_id = crawl_job_id
        plan.consumed_at = consumed_at

    def mark_expired(self, plan: CrawlDispatchPlan) -> None:
        plan.state = "expired"

    def expire_due(self, db: Session, *, now: datetime) -> int:
        rows = (
            db.query(CrawlDispatchPlan)
            .filter(
                CrawlDispatchPlan.state == "prepared",
                CrawlDispatchPlan.expires_at <= now,
            )
            .with_for_update()
            .all()
        )
        for row in rows:
            self.mark_expired(row)
        if rows:
            db.flush()
        return len(rows)

    def delete_expired_before(
        self,
        db: Session,
        *,
        retention_cutoff: datetime,
    ) -> int:
        return int(
            db.query(CrawlDispatchPlan)
            .filter(
                CrawlDispatchPlan.state == "expired",
                CrawlDispatchPlan.expires_at < retention_cutoff,
            )
            .delete(synchronize_session=False)
        )

    @staticmethod
    def _target_model(target: DispatchPlanTargetV1) -> CrawlDispatchPlanTarget:
        return CrawlDispatchPlanTarget(
            source_site=target.source_site,
            source_job_id=target.source_job_id,
            selection_order=target.selection_order,
            eligibility_fingerprint=target.eligibility_fingerprint,
            eligibility_status=target.eligibility_status,
            status_metadata=dict(target.status_metadata),
            rows=[
                CrawlDispatchPlanTargetRow(
                    crawl_job_listing_id=row.crawl_job_listing_id,
                    row_order=row.row_order,
                    eligibility_fingerprint=row.eligibility_fingerprint,
                    eligibility_status=row.eligibility_status,
                    status_metadata=dict(row.status_metadata),
                )
                for row in target.rows
            ],
        )
