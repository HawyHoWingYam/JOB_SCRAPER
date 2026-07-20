from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.crawl_control.contracts import CrawlScopeErrorPayloadV1
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanCleanupResultV1,
    DispatchPlanContentV1,
    DispatchPlanPreparationV1,
    DispatchPlanReadinessV1,
    DispatchPlanSnapshotV1,
    DispatchPlanTargetRowV1,
    DispatchPlanTargetV1,
    ExecutionAuthorityV1,
    dispatch_plan_fingerprint,
)
from app.crawl_control.dispatch_plan_repository import DispatchPlanRepository
from app.crawl_control.detail_runtime import DetailBacklogSnapshotBuilder
from app.crawl_control.errors import (
    DispatchPlanAlreadyConsumedError,
    DispatchPlanExpiredError,
    DispatchPlanFingerprintMismatchError,
    DispatchPlanNotFoundError,
    DispatchPlanStaleError,
)
from app.crawl_control.scope_service import evaluate_listing_workload
from app.models.crawl_dispatch_plan import CrawlDispatchPlan
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScheduleExecution
from app.utils.time import utc_now


DEFAULT_DISPATCH_PLAN_TTL = timedelta(minutes=15)
MAX_DISPATCH_PLAN_TTL = timedelta(hours=24)
DEFAULT_EXPIRED_PLAN_RETENTION = timedelta(days=7)


class DispatchPlanService:
    """Prepare, validate, consume, and load immutable execution authority."""

    def __init__(
        self,
        db: Session,
        *,
        repository: DispatchPlanRepository | None = None,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] | None = None,
        uuid_factory: Callable[[], UUID] = uuid4,
        detail_backlog_builder: DetailBacklogSnapshotBuilder | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or DispatchPlanRepository()
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._uuid_factory = uuid_factory
        self._detail_backlog_builder = (
            detail_backlog_builder or DetailBacklogSnapshotBuilder()
        )

    def prepare(
        self,
        content: DispatchPlanContentV1,
        *,
        readiness: DispatchPlanReadinessV1,
        targets: tuple[DispatchPlanTargetV1, ...] | None = None,
        prepared_by: str,
        ttl: timedelta = DEFAULT_DISPATCH_PLAN_TTL,
        confirmation_required: bool | None = None,
    ) -> DispatchPlanPreparationV1:
        prepared_by = str(prepared_by or "").strip()
        if not prepared_by:
            raise ValueError("Dispatch Plan preparer is required")
        if ttl <= timedelta(0) or ttl > MAX_DISPATCH_PLAN_TTL:
            raise ValueError("Dispatch Plan TTL must be positive and no more than 24 hours")
        now = self._now()
        if content.listing_settings is not None:
            evaluate_listing_workload(
                content.resolved_scope,
                content.listing_settings,
                enforce=True,
            )
            if targets:
                raise ValueError("Listing Dispatch Plans cannot contain detail targets")
            targets = ()
        else:
            if targets is not None:
                raise ValueError(
                    "Detail target membership is selected by Dispatch Plan preparation"
                )
            frozen_backlog = self._detail_backlog_builder.freeze(
                self.db,
                content=content,
                cutoff_at=now,
            )
            content = frozen_backlog.content
            targets = frozen_backlog.targets

        assert targets is not None
        if (
            content.crawl_phase == "detail"
            and not targets
            and readiness.status == "ready"
        ):
            detail_settings = content.detail_settings
            assert detail_settings is not None
            readiness = DispatchPlanReadinessV1(
                status="blocked",
                checked_at=readiness.checked_at,
                blocking_errors=(
                    CrawlScopeErrorPayloadV1(
                        code="DETAIL_BACKLOG_EMPTY",
                        message="No eligible detail targets were found at review cutoff",
                        context={
                            "source_site": content.source_site,
                            "backlog_scope": detail_settings.backlog_scope.kind,
                        },
                    ),
                ),
                capabilities=dict(readiness.capabilities),
            )
        plan_id = self._uuid_factory()
        confirmation_required = self._confirmation_required(
            content=content,
            readiness=readiness,
            requested=confirmation_required,
        )
        confirmation_token = (
            self._token_factory() if confirmation_required else None
        )
        if confirmation_token is not None and len(confirmation_token) < 20:
            raise ValueError("Dispatch Plan confirmation token is too short")
        expires_at = now + ttl
        fingerprint = dispatch_plan_fingerprint(
            plan_id=plan_id,
            content=content,
            readiness=readiness,
            targets=targets,
            confirmation_required=confirmation_required,
            prepared_by=prepared_by,
            prepared_at=now,
            expires_at=expires_at,
        )
        snapshot = DispatchPlanSnapshotV1(
            plan_id=plan_id,
            state="prepared",
            content=content,
            readiness=readiness,
            targets=targets,
            detail_target_count=len(targets),
            plan_fingerprint=fingerprint,
            confirmation_required=confirmation_required,
            prepared_by=prepared_by,
            prepared_at=now,
            expires_at=expires_at,
        )

        try:
            plan = self.repository.add_prepared(
                self.db,
                plan_id=plan_id,
                content=content,
                readiness=readiness,
                targets=targets,
                plan_fingerprint=fingerprint,
                confirmation_required=confirmation_required,
                confirmation_token_hash=(
                    self._token_hash(confirmation_token)
                    if confirmation_token is not None
                    else None
                ),
                prepared_by=prepared_by,
                prepared_at=now,
                expires_at=expires_at,
            )
            self.db.commit()
            self.db.refresh(plan)
        except Exception:
            self.db.rollback()
            raise
        return DispatchPlanPreparationV1(
            plan=snapshot,
            confirmation_token=confirmation_token,
        )

    def get(self, plan_id: UUID) -> DispatchPlanSnapshotV1:
        try:
            plan = self.repository.get(self.db, plan_id, for_update=True)
            if plan is None:
                raise DispatchPlanNotFoundError(plan_id)
            snapshot = self._validated_snapshot(plan)
            if snapshot.state == "prepared" and snapshot.expires_at <= self._now():
                self.repository.mark_expired(plan)
                self.db.commit()
                snapshot = self._validated_snapshot(plan)
            else:
                self.db.rollback()
            return snapshot
        except Exception:
            self.db.rollback()
            raise

    def consume(
        self,
        plan_id: UUID,
        *,
        crawl_job_id: UUID,
        confirmation_token: str | None,
        expected_plan_fingerprint: str | None = None,
    ) -> DispatchPlanSnapshotV1:
        try:
            crawl_job = (
                self.db.query(CrawlJob)
                .filter(CrawlJob.id == crawl_job_id)
                .with_for_update()
                .one_or_none()
            )
            if crawl_job is None:
                raise DispatchPlanStaleError(
                    "Dispatch Plan Crawl Job no longer exists",
                    plan_id=plan_id,
                    reason="crawl_job_missing",
                )
            plan = self.repository.get(self.db, plan_id, for_update=True)
            if plan is None:
                raise DispatchPlanNotFoundError(plan_id)
            snapshot = self._validated_snapshot(plan)
            if snapshot.state == "consumed":
                raise DispatchPlanAlreadyConsumedError(plan_id)
            if snapshot.state == "expired":
                raise DispatchPlanExpiredError(plan_id)
            if snapshot.expires_at <= self._now():
                self.repository.mark_expired(plan)
                self.db.commit()
                raise DispatchPlanExpiredError(plan_id)
            if snapshot.readiness.status != "ready":
                raise DispatchPlanStaleError(
                    "Dispatch Plan is not runtime-ready",
                    plan_id=plan_id,
                    reason="readiness_blocked",
                )
            self._validate_confirmation(plan, confirmation_token)
            if (
                expected_plan_fingerprint is not None
                and expected_plan_fingerprint != snapshot.plan_fingerprint
            ):
                raise DispatchPlanFingerprintMismatchError(
                    plan_id=plan_id,
                    crawl_job_id=crawl_job_id,
                )

            self._validate_job_link(snapshot, crawl_job)
            self.repository.mark_consumed(
                plan,
                crawl_job_id=crawl_job.id,
                consumed_at=self._now(),
            )
            self.db.flush()
            self.db.commit()
            return self._validated_snapshot(plan)
        except DispatchPlanExpiredError:
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

    def load_execution_authority(
        self,
        crawl_job_id: UUID,
    ) -> ExecutionAuthorityV1 | None:
        crawl_job = (
            self.db.query(CrawlJob)
            .filter(CrawlJob.id == crawl_job_id)
            .one_or_none()
        )
        if crawl_job is None:
            raise DispatchPlanStaleError(
                "Crawl Job no longer exists",
                plan_id=None,
                reason="crawl_job_missing",
            )
        if (
            crawl_job.dispatch_plan_id is None
            and crawl_job.dispatch_plan_fingerprint is None
        ):
            return None
        if (
            crawl_job.dispatch_plan_id is None
            or crawl_job.dispatch_plan_fingerprint is None
        ):
            raise DispatchPlanFingerprintMismatchError(
                plan_id=crawl_job.dispatch_plan_id,
                crawl_job_id=crawl_job.id,
            )

        plan = self.repository.get(self.db, crawl_job.dispatch_plan_id)
        if plan is None:
            raise DispatchPlanNotFoundError(crawl_job.dispatch_plan_id)
        snapshot = self._validated_snapshot(plan, crawl_job_id=crawl_job.id)
        if snapshot.state != "consumed":
            raise DispatchPlanStaleError(
                "Crawl Job Dispatch Plan has not been consumed",
                plan_id=snapshot.plan_id,
                reason="plan_not_consumed",
            )
        self._validate_job_link(snapshot, crawl_job)
        self._validate_schedule_execution_links(snapshot, crawl_job)
        return ExecutionAuthorityV1(
            crawl_job_id=crawl_job.id,
            dispatch_plan=snapshot,
        )

    @staticmethod
    def require_worker_runtime_supported(
        authority: ExecutionAuthorityV1 | None,
        *,
        supported_phases: Collection[str] = (),
    ) -> None:
        """Allow only phase adapters that consume immutable plan authority directly."""

        if authority is None:
            return
        if authority.dispatch_plan.content.crawl_phase in supported_phases:
            return
        raise DispatchPlanStaleError(
            "Versioned worker runtime adapter is not available for this phase",
            plan_id=authority.dispatch_plan.plan_id,
            reason="runtime_authority_adapter_required",
        )

    def cleanup_expired(
        self,
        *,
        retention: timedelta = DEFAULT_EXPIRED_PLAN_RETENTION,
    ) -> DispatchPlanCleanupResultV1:
        if retention < timedelta(0):
            raise ValueError("Dispatch Plan cleanup retention cannot be negative")
        now = self._now()
        try:
            expired_count = self.repository.expire_due(self.db, now=now)
            deleted_count = self.repository.delete_expired_before(
                self.db,
                retention_cutoff=now - retention,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return DispatchPlanCleanupResultV1(
            expired_count=expired_count,
            deleted_count=deleted_count,
            completed_at=now,
        )

    def _validated_snapshot(
        self,
        plan: CrawlDispatchPlan,
        *,
        crawl_job_id: UUID | None = None,
    ) -> DispatchPlanSnapshotV1:
        try:
            snapshot = self._snapshot(plan)
        except (TypeError, ValueError) as exc:
            raise DispatchPlanFingerprintMismatchError(
                plan_id=plan.id,
                crawl_job_id=crawl_job_id,
            ) from exc
        return snapshot

    def _snapshot(self, plan: CrawlDispatchPlan) -> DispatchPlanSnapshotV1:
        content = DispatchPlanContentV1(
            source_site=plan.source_site,
            crawl_phase=plan.crawl_phase,
            trigger_kind=plan.trigger_kind,
            automation_id=plan.automation_id_snapshot,
            expected_automation_revision=plan.expected_automation_revision,
            catalog_revision_id=plan.catalog_revision_id,
            authored_scope=plan.authored_scope,
            resolved_scope=plan.resolved_scope,
            listing_settings=plan.listing_settings,
            detail_settings=plan.detail_settings,
        )
        readiness = DispatchPlanReadinessV1.model_validate(plan.readiness)
        targets = tuple(
            DispatchPlanTargetV1(
                source_site=target.source_site,
                source_job_id=target.source_job_id,
                selection_order=target.selection_order,
                eligibility_fingerprint=target.eligibility_fingerprint,
                eligibility_status=target.eligibility_status,
                status_metadata=dict(target.status_metadata or {}),
                rows=tuple(
                    DispatchPlanTargetRowV1(
                        crawl_job_listing_id=row.crawl_job_listing_id,
                        row_order=row.row_order,
                        eligibility_fingerprint=row.eligibility_fingerprint,
                        eligibility_status=row.eligibility_status,
                        status_metadata=dict(row.status_metadata or {}),
                    )
                    for row in sorted(target.rows, key=lambda value: value.row_order)
                ),
            )
            for target in sorted(plan.targets, key=lambda value: value.selection_order)
        )
        return DispatchPlanSnapshotV1(
            plan_id=plan.id,
            state=plan.state,
            content=content,
            readiness=readiness,
            targets=targets,
            detail_target_count=plan.detail_target_count,
            plan_fingerprint=plan.plan_fingerprint,
            confirmation_required=plan.confirmation_required,
            prepared_by=plan.prepared_by,
            prepared_at=self._aware_utc(plan.prepared_at),
            expires_at=self._aware_utc(plan.expires_at),
            consumed_at=(
                self._aware_utc(plan.consumed_at)
                if plan.consumed_at is not None
                else None
            ),
            crawl_job_id=plan.crawl_job_id,
        )

    @staticmethod
    def _validate_job_link(
        snapshot: DispatchPlanSnapshotV1,
        crawl_job: CrawlJob,
    ) -> None:
        if (
            crawl_job.dispatch_plan_id != snapshot.plan_id
            or crawl_job.dispatch_plan_fingerprint != snapshot.plan_fingerprint
            or crawl_job.source_site != snapshot.content.source_site
        ):
            raise DispatchPlanFingerprintMismatchError(
                plan_id=snapshot.plan_id,
                crawl_job_id=crawl_job.id,
            )
        if (
            snapshot.state == "consumed"
            and snapshot.crawl_job_id != crawl_job.id
        ):
            raise DispatchPlanFingerprintMismatchError(
                plan_id=snapshot.plan_id,
                crawl_job_id=crawl_job.id,
            )

    def _validate_schedule_execution_links(
        self,
        snapshot: DispatchPlanSnapshotV1,
        crawl_job: CrawlJob,
    ) -> None:
        executions = (
            self.db.query(ScheduleExecution)
            .filter(ScheduleExecution.crawl_job_id == crawl_job.id)
            .all()
        )
        for execution in executions:
            if (
                execution.dispatch_plan_id != snapshot.plan_id
                or execution.dispatch_plan_fingerprint != snapshot.plan_fingerprint
            ):
                raise DispatchPlanFingerprintMismatchError(
                    plan_id=snapshot.plan_id,
                    crawl_job_id=crawl_job.id,
                )

    @staticmethod
    def _validate_confirmation(
        plan: CrawlDispatchPlan,
        confirmation_token: str | None,
    ) -> None:
        if not plan.confirmation_required:
            return
        supplied_hash = (
            DispatchPlanService._token_hash(confirmation_token)
            if confirmation_token is not None
            else ""
        )
        if plan.confirmation_token_hash is None or not secrets.compare_digest(
            supplied_hash,
            plan.confirmation_token_hash,
        ):
            raise DispatchPlanStaleError(
                "Dispatch Plan confirmation token is invalid",
                plan_id=plan.id,
                reason="confirmation_token_mismatch",
            )

    @staticmethod
    def _confirmation_required(
        *,
        content: DispatchPlanContentV1,
        readiness: DispatchPlanReadinessV1,
        requested: bool | None,
    ) -> bool:
        required = (
            readiness.status == "ready"
            and content.trigger_kind != "scheduled_automation"
        )
        if requested is not None and requested != required:
            raise ValueError(
                "Only ready human-reviewed Dispatch Plans require confirmation"
            )
        return required

    def _now(self) -> datetime:
        return self._aware_utc(self._clock())

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _token_hash(review_token: str) -> str:
        return hashlib.sha256(review_token.encode("utf-8")).hexdigest()
