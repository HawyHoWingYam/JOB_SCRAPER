from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.crawl_cancellation import ACTIVE_MANUAL_DETAIL_STATUSES
from app.crawl_control.automation_contracts import AutomationSnapshotV1
from app.crawl_control.automation_repository import AutomationRepository
from app.crawl_control.contracts import CrawlScopeErrorPayloadV1, JsonScalar
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanCleanupResultV1,
    DispatchPlanContentV1,
    DispatchPlanPreparationV1,
    DispatchPlanReadinessV1,
    DispatchPlanSnapshotV1,
    DispatchPlanTargetRowV1,
    DispatchPlanTargetV1,
    DispatchPlanRunRequestV1,
    DispatchTriggerKind,
    ExecutionAuthorityV1,
    OneOffRunV1,
    SavedAutomationRunV1,
    dispatch_plan_fingerprint,
)
from app.crawl_control.dispatch_plan_repository import DispatchPlanRepository
from app.crawl_control.detail_runtime import (
    DetailBacklogSnapshotBuilder,
    detail_row_eligibility_fingerprint,
    detail_row_runtime_identity_fingerprint,
)
from app.crawl_control.errors import (
    AutomationNotFoundError,
    AutomationRevisionConflictError,
    AutomationTransitionInvalidError,
    DetailRunConflictError,
    DispatchPlanAlreadyConsumedError,
    DispatchPlanExpiredError,
    DispatchPlanFingerprintMismatchError,
    DispatchPlanNotFoundError,
    DispatchPlanStaleError,
)
from app.crawl_control.scope_service import evaluate_listing_workload
from app.models.crawl_dispatch_plan import CrawlDispatchPlan
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.repositories.crawl_job_listing_repository import (
    CrawlJobListingRepository,
)
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.services.scraper_pacing_settings_service import (
    ScraperPacingSettingsService,
)
from app.utils.time import utc_now


DEFAULT_DISPATCH_PLAN_TTL = timedelta(minutes=15)
MAX_DISPATCH_PLAN_TTL = timedelta(hours=24)
DEFAULT_EXPIRED_PLAN_RETENTION = timedelta(days=7)

_DETAIL_PACING_CAPABILITY_FIELDS = (
    "interval_min_seconds",
    "interval_max_seconds",
    "burst_size",
    "burst_pause_seconds",
)


def _ensure_runtime_readiness(*, crawl_mode: str, source_site: str) -> None:
    # Lazy import avoids a module cycle through CrawlJobExecutionLauncher.
    from app.services.headed_crawl_runtime import (
        ensure_headed_crawl_worker_available,
    )

    ensure_headed_crawl_worker_available(
        crawl_mode=crawl_mode,
        source_site=source_site,
    )


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
        automation_repository: AutomationRepository | None = None,
        crawl_job_repository: CrawlJobRepository | None = None,
        crawl_job_listing_repository: CrawlJobListingRepository | None = None,
        source_catalog_repository: SourceCatalogRepository | None = None,
        scope_service=None,
        runtime_readiness_check: Callable[..., None] = _ensure_runtime_readiness,
    ) -> None:
        self.db = db
        self.repository = repository or DispatchPlanRepository()
        self.automation_repository = (
            automation_repository or AutomationRepository()
        )
        self.crawl_job_repository = crawl_job_repository or CrawlJobRepository()
        self.crawl_job_listing_repository = (
            crawl_job_listing_repository or CrawlJobListingRepository()
        )
        self.source_catalog_repository = (
            source_catalog_repository or SourceCatalogRepository()
        )
        if scope_service is None:
            from app.services.source_catalog_service import SourceCatalogService

            from app.crawl_control.scope_service import CrawlScopeService

            scope_service = CrawlScopeService(SourceCatalogService(db))
        self.scope_service = scope_service
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._uuid_factory = uuid_factory
        self._runtime_readiness_check = runtime_readiness_check
        self._detail_backlog_builder = (
            detail_backlog_builder or DetailBacklogSnapshotBuilder()
        )

    def prepare_run(
        self,
        request: DispatchPlanRunRequestV1,
        *,
        prepared_by: str,
        trigger_kind: DispatchTriggerKind | None = None,
        ttl: timedelta = DEFAULT_DISPATCH_PLAN_TTL,
        auto_commit: bool = True,
        automation: ScrapeSchedule | None = None,
    ) -> DispatchPlanPreparationV1:
        """Resolve a One-off or saved Automation into one immutable plan."""

        try:
            if isinstance(request, OneOffRunV1):
                if automation is not None:
                    raise ValueError("One-off run cannot receive an Automation")
                if trigger_kind not in {None, "one_off"}:
                    raise ValueError("One-off run trigger kind is invalid")
                listing_settings = request.listing_settings
                preview = self.scope_service.preview(
                    request.scope,
                    listing_settings=listing_settings,
                )
                content = DispatchPlanContentV1(
                    source_site=request.scope.source_site,
                    crawl_phase=(
                        "listing" if listing_settings is not None else "detail"
                    ),
                    trigger_kind="one_off",
                    catalog_revision_id=preview.resolved_scope.catalog_revision_id,
                    authored_scope=preview.resolved_scope.authored_scope,
                    resolved_scope=preview.resolved_scope,
                    listing_settings=listing_settings,
                    detail_settings=request.detail_settings,
                )
            elif isinstance(request, SavedAutomationRunV1):
                effective_trigger = trigger_kind or "saved_automation"
                if effective_trigger not in {
                    "saved_automation",
                    "scheduled_automation",
                }:
                    raise ValueError("Saved Automation run trigger kind is invalid")
                automation = automation or self.automation_repository.get(
                    self.db,
                    request.automation_id,
                    for_update=True,
                )
                if automation is None:
                    raise AutomationNotFoundError(request.automation_id)
                if automation.id != request.automation_id:
                    raise ValueError("Automation object and request ID differ")
                if int(automation.revision) != request.expected_revision:
                    raise AutomationRevisionConflictError(
                        automation_id=automation.id,
                        expected_revision=request.expected_revision,
                        current_revision=int(automation.revision),
                    )
                if automation.scope_contract is None:
                    raise AutomationTransitionInvalidError(
                        current_state="legacy",
                        operation="versioned_dispatch",
                    )
                allowed_states = (
                    {"active"}
                    if effective_trigger == "scheduled_automation"
                    else {"active", "paused"}
                )
                if automation.lifecycle_state not in allowed_states:
                    raise AutomationTransitionInvalidError(
                        current_state=str(automation.lifecycle_state),
                        operation=(
                            "scheduled_dispatch"
                            if effective_trigger == "scheduled_automation"
                            else "run_saved_configuration"
                        ),
                    )
                revision_row = self.automation_repository.get_revision(
                    self.db,
                    automation_id=automation.id,
                    revision=request.expected_revision,
                )
                if revision_row is None:
                    raise DispatchPlanStaleError(
                        "Automation revision snapshot is missing",
                        reason="automation_snapshot_missing",
                    )
                automation_snapshot = AutomationSnapshotV1.model_validate(
                    revision_row.snapshot
                )
                if (
                    automation_snapshot.automation_id != automation.id
                    or automation_snapshot.revision != request.expected_revision
                    or automation_snapshot.fingerprint
                    != revision_row.snapshot_fingerprint
                ):
                    raise DispatchPlanStaleError(
                        "Automation revision snapshot is invalid",
                        reason="automation_snapshot_invalid",
                    )
                configuration = automation_snapshot.configuration
                resolved_scope = self.scope_service.resolve_for_run(
                    configuration.scope,
                    listing_settings=configuration.listing_settings,
                )
                content = DispatchPlanContentV1(
                    source_site=configuration.scope.source_site,
                    crawl_phase=configuration.crawl_phase,
                    trigger_kind=effective_trigger,
                    automation_id=automation.id,
                    expected_automation_revision=request.expected_revision,
                    catalog_revision_id=resolved_scope.catalog_revision_id,
                    authored_scope=resolved_scope.authored_scope,
                    resolved_scope=resolved_scope,
                    listing_settings=configuration.listing_settings,
                    detail_settings=configuration.detail_settings,
                )
            else:
                raise TypeError("Unsupported Dispatch Plan run request")

            readiness = self._build_runtime_readiness(content)
            return self.prepare(
                content,
                readiness=readiness,
                prepared_by=prepared_by,
                ttl=ttl,
                auto_commit=auto_commit,
            )
        except Exception:
            if auto_commit:
                self.db.rollback()
            raise

    def prepare(
        self,
        content: DispatchPlanContentV1,
        *,
        readiness: DispatchPlanReadinessV1,
        targets: tuple[DispatchPlanTargetV1, ...] | None = None,
        prepared_by: str,
        ttl: timedelta = DEFAULT_DISPATCH_PLAN_TTL,
        confirmation_required: bool | None = None,
        auto_commit: bool = True,
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
            if auto_commit:
                self.db.commit()
                self.db.refresh(plan)
        except Exception:
            if auto_commit:
                self.db.rollback()
            raise
        return DispatchPlanPreparationV1(
            plan=snapshot,
            confirmation_token=confirmation_token,
        )

    def lock_prepared_for_dispatch(
        self,
        plan_id: UUID,
        *,
        confirmation_token: str | None,
        expected_plan_fingerprint: str | None = None,
    ) -> tuple[CrawlDispatchPlan, DispatchPlanSnapshotV1]:
        """Lock and validate a prepared plan without committing its transaction."""

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
            self.db.flush()
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
                crawl_job_id=None,
            )
        return plan, snapshot

    def persist_expired_plan_after_rollback(self, plan_id: UUID) -> None:
        """Roll back caller work before durably recording one due plan expiry."""

        self.db.rollback()
        try:
            plan = self.repository.get(self.db, plan_id, for_update=True)
            if plan is None:
                self.db.rollback()
                return
            snapshot = self._validated_snapshot(plan)
            if snapshot.state == "prepared" and snapshot.expires_at <= self._now():
                self.repository.mark_expired(plan)
                self.db.commit()
                return
            self.db.rollback()
        except Exception:
            self.db.rollback()
            raise

    def lock_current_catalog(
        self,
        snapshot: DispatchPlanSnapshotV1,
    ) -> None:
        pointer = self.source_catalog_repository.get_active_pointer_for_update(
            self.db,
            source_site=snapshot.content.source_site,
        )
        if pointer is None:
            raise DispatchPlanStaleError(
                "Dispatch Plan source catalog is no longer published",
                plan_id=snapshot.plan_id,
                reason="catalog_unpublished",
            )
        if pointer.revision_id != snapshot.content.catalog_revision_id:
            raise DispatchPlanStaleError(
                "Dispatch Plan source catalog revision changed before dispatch",
                plan_id=snapshot.plan_id,
                reason="catalog_revision_changed",
            )

    def lock_current_automation(
        self,
        snapshot: DispatchPlanSnapshotV1,
        *,
        automation: ScrapeSchedule | None = None,
    ) -> tuple[ScrapeSchedule | None, dict | None]:
        content = snapshot.content
        if content.automation_id is None:
            if automation is not None:
                raise ValueError("One-off Dispatch Plan cannot bind an Automation")
            return None, None
        if automation is not None and automation.id != content.automation_id:
            raise DispatchPlanStaleError(
                "Dispatch Plan Automation identity changed",
                plan_id=snapshot.plan_id,
                reason="automation_identity_changed",
            )
        automation = self.automation_repository.get(
            self.db,
            content.automation_id,
            for_update=True,
        )
        if automation is None:
            raise DispatchPlanStaleError(
                "Dispatch Plan Automation no longer exists",
                plan_id=snapshot.plan_id,
                reason="automation_missing",
            )
        if automation.id != content.automation_id:
            raise DispatchPlanStaleError(
                "Dispatch Plan Automation identity changed",
                plan_id=snapshot.plan_id,
                reason="automation_identity_changed",
            )
        expected_revision = content.expected_automation_revision
        assert expected_revision is not None
        if int(automation.revision) != expected_revision:
            raise AutomationRevisionConflictError(
                automation_id=automation.id,
                expected_revision=expected_revision,
                current_revision=int(automation.revision),
            )
        allowed_states = (
            {"active"}
            if content.trigger_kind == "scheduled_automation"
            else {"active", "paused"}
        )
        if automation.lifecycle_state not in allowed_states:
            raise AutomationTransitionInvalidError(
                current_state=str(automation.lifecycle_state),
                operation=(
                    "scheduled_dispatch"
                    if content.trigger_kind == "scheduled_automation"
                    else "run_saved_configuration"
                ),
            )
        revision_row = self.automation_repository.get_revision(
            self.db,
            automation_id=automation.id,
            revision=expected_revision,
        )
        if revision_row is None:
            raise DispatchPlanStaleError(
                "Dispatch Plan Automation revision snapshot is missing",
                plan_id=snapshot.plan_id,
                reason="automation_snapshot_missing",
            )
        automation_snapshot = AutomationSnapshotV1.model_validate(
            revision_row.snapshot
        )
        if (
            automation_snapshot.automation_id != automation.id
            or automation_snapshot.revision != expected_revision
            or automation_snapshot.fingerprint != revision_row.snapshot_fingerprint
        ):
            raise DispatchPlanStaleError(
                "Dispatch Plan Automation revision snapshot is invalid",
                plan_id=snapshot.plan_id,
                reason="automation_snapshot_invalid",
            )
        return automation, dict(revision_row.snapshot)

    def revalidate_runtime_readiness(
        self,
        snapshot: DispatchPlanSnapshotV1,
    ) -> None:
        content = snapshot.content
        settings = content.listing_settings or content.detail_settings
        assert settings is not None
        try:
            self._runtime_readiness_check(
                crawl_mode=settings.crawl_mode,
                source_site=content.source_site,
            )
        except Exception as exc:
            from app.services.headed_crawl_runtime import (
                HeadedCrawlWorkerUnavailableError,
            )

            if not isinstance(exc, HeadedCrawlWorkerUnavailableError):
                raise
            raise DispatchPlanStaleError(
                "Dispatch Plan runtime readiness changed before dispatch",
                plan_id=snapshot.plan_id,
                reason="runtime_readiness_changed",
            ) from exc
        if content.listing_settings is not None:
            evaluate_listing_workload(
                content.resolved_scope,
                content.listing_settings,
                enforce=True,
            )
            return
        if self.detail_pacing_payload(snapshot) is None:
            raise DispatchPlanStaleError(
                "Dispatch Plan detail pacing snapshot is missing",
                plan_id=snapshot.plan_id,
                reason="detail_pacing_missing",
            )
        if content.trigger_kind != "one_off":
            return
        ScraperPacingSettingsService(self.db).resolve(
            content.source_site,
            for_update=True,
        )
        conflicts = (
            self.crawl_job_repository.list_active_manual_detail_jobs_for_update(
                self.db,
                source_site=content.source_site,
                statuses=ACTIVE_MANUAL_DETAIL_STATUSES,
            )
        )
        if conflicts:
            raise DetailRunConflictError(
                source_site=content.source_site,
                crawl_job_id=conflicts[0].id,
            )

    def claim_detail_membership(
        self,
        snapshot: DispatchPlanSnapshotV1,
        *,
        crawl_job_id: UUID,
    ) -> None:
        if snapshot.content.crawl_phase != "detail":
            return
        listing_ids = tuple(
            row.crawl_job_listing_id
            for target in snapshot.targets
            for row in target.rows
        )
        rows_by_id = {
            row.id: row
            for row in self.crawl_job_listing_repository.list_by_ids(
                self.db,
                listing_ids=listing_ids,
                for_update=True,
            )
        }
        if len(rows_by_id) != len(listing_ids):
            raise DispatchPlanStaleError(
                "Dispatch Plan detail membership is no longer complete",
                plan_id=snapshot.plan_id,
                reason="detail_target_row_missing",
            )
        claimed_at = self._now()
        for target in snapshot.targets:
            for frozen_row in target.rows:
                row = rows_by_id[frozen_row.crawl_job_listing_id]
                if (
                    str(row.source_site).strip().lower()
                    != snapshot.content.source_site
                    or str(row.source_job_id).strip() != target.source_job_id
                ):
                    raise DispatchPlanStaleError(
                        "Dispatch Plan detail target identity changed",
                        plan_id=snapshot.plan_id,
                        reason="detail_target_identity_changed",
                    )
                expected_runtime_identity = str(
                    frozen_row.status_metadata.get(
                        "runtime_identity_fingerprint"
                    )
                    or ""
                )
                if (
                    detail_row_runtime_identity_fingerprint(row)
                    != expected_runtime_identity
                ):
                    raise DispatchPlanStaleError(
                        "Dispatch Plan detail target source inputs changed",
                        plan_id=snapshot.plan_id,
                        reason="detail_target_inputs_changed",
                    )
                if (
                    detail_row_eligibility_fingerprint(row)
                    != frozen_row.eligibility_fingerprint
                ):
                    raise DispatchPlanStaleError(
                        "Dispatch Plan detail target eligibility changed",
                        plan_id=snapshot.plan_id,
                        reason="detail_target_eligibility_changed",
                    )
                row.detail_status = "running"
                row.last_detail_crawl_job_id = crawl_job_id
                row.detail_started_at = claimed_at
                row.detail_completed_at = None
                row.detail_error_message = None
        self.db.flush()

    def mark_consumed_in_transaction(
        self,
        plan: CrawlDispatchPlan,
        snapshot: DispatchPlanSnapshotV1,
        *,
        crawl_job: CrawlJob,
    ) -> DispatchPlanSnapshotV1:
        self._validate_job_link(snapshot, crawl_job)
        self.repository.mark_consumed(
            plan,
            crawl_job_id=crawl_job.id,
            consumed_at=self._now(),
        )
        self.db.flush()
        return self._validated_snapshot(plan, crawl_job_id=crawl_job.id)

    @staticmethod
    def detail_pacing_payload(
        snapshot: DispatchPlanSnapshotV1,
    ) -> dict[str, float | int] | None:
        capabilities = snapshot.readiness.capabilities
        interval_min = capabilities.get("detail_pacing_interval_min_seconds")
        interval_max = capabilities.get("detail_pacing_interval_max_seconds")
        burst_size = capabilities.get("detail_pacing_burst_size")
        burst_pause = capabilities.get("detail_pacing_burst_pause_seconds")
        if any(
            value is None
            for value in (
                interval_min,
                interval_max,
                burst_size,
                burst_pause,
            )
        ):
            return None
        assert interval_min is not None
        assert interval_max is not None
        assert burst_size is not None
        assert burst_pause is not None
        return {
            "interval_min_seconds": float(interval_min),
            "interval_max_seconds": float(interval_max),
            "burst_size": int(burst_size),
            "burst_pause_seconds": float(burst_pause),
        }

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
            plan, snapshot = self.lock_prepared_for_dispatch(
                plan_id,
                confirmation_token=confirmation_token,
                expected_plan_fingerprint=expected_plan_fingerprint,
            )
            consumed = self.mark_consumed_in_transaction(
                plan,
                snapshot,
                crawl_job=crawl_job,
            )
            self.db.commit()
            return consumed
        except DispatchPlanExpiredError:
            self.persist_expired_plan_after_rollback(plan_id)
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

    def _build_runtime_readiness(
        self,
        content: DispatchPlanContentV1,
    ) -> DispatchPlanReadinessV1:
        from app.services.headed_crawl_runtime import (
            HeadedCrawlWorkerUnavailableError,
        )

        settings = content.listing_settings or content.detail_settings
        assert settings is not None
        blocking_errors: list[CrawlScopeErrorPayloadV1] = []
        capabilities: dict[str, JsonScalar] = {
            "crawl_mode": settings.crawl_mode,
            "runtime_ready": True,
        }
        try:
            self._runtime_readiness_check(
                crawl_mode=settings.crawl_mode,
                source_site=content.source_site,
            )
        except HeadedCrawlWorkerUnavailableError as exc:
            capabilities["runtime_ready"] = False
            blocking_errors.append(
                CrawlScopeErrorPayloadV1(
                    code="HEADED_WORKER_UNAVAILABLE",
                    message=str(exc),
                    context={"source_site": content.source_site},
                )
            )

        if content.crawl_phase == "detail":
            pacing = ScraperPacingSettingsService(self.db).resolve(
                content.source_site,
                for_update=True,
            ).to_payload()
            for field in _DETAIL_PACING_CAPABILITY_FIELDS:
                capabilities[f"detail_pacing_{field}"] = pacing[field]
            if content.trigger_kind == "one_off":
                conflicts = (
                    self.crawl_job_repository.list_active_manual_detail_jobs_for_update(
                        self.db,
                        source_site=content.source_site,
                        statuses=ACTIVE_MANUAL_DETAIL_STATUSES,
                    )
                )
                if conflicts:
                    blocking_errors.append(
                        DetailRunConflictError(
                            source_site=content.source_site,
                            crawl_job_id=conflicts[0].id,
                        ).to_payload()
                    )

        return DispatchPlanReadinessV1(
            status="blocked" if blocking_errors else "ready",
            checked_at=self._now(),
            blocking_errors=tuple(blocking_errors),
            capabilities=capabilities,
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
