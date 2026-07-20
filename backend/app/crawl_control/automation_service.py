from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Literal
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.crawl_control.automation_contracts import (
    AutomationConfigurationV1,
    AutomationDeleteImpactV1,
    AutomationDeleteReviewGrantV1,
    AutomationLifecycleState,
    AutomationProjectionV1,
    AutomationSnapshotV1,
)
from app.crawl_control.automation_repository import AutomationRepository
from app.crawl_control.contracts import CrawlScopeErrorPayloadV1
from app.crawl_control.errors import (
    AutomationDeleteReviewStaleError,
    AutomationNotFoundError,
    AutomationRevisionConflictError,
    AutomationTransitionInvalidError,
    ScopeRuleInvalidError,
)
from app.crawl_control.scope_service import CrawlScopeService
from app.crawl_modes import get_supported_crawl_modes
from app.models.schedule import AutomationDeleteReview, ScrapeSchedule
from app.services.source_catalog_service import SourceCatalogService
from app.utils.time import utc_now


class AutomationService:
    """Own Automation revisions, lifecycle, optimistic concurrency, and deletion."""

    def __init__(
        self,
        db: Session,
        *,
        repository: AutomationRepository | None = None,
        scope_service: CrawlScopeService | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or AutomationRepository()
        self.scope_service = scope_service or CrawlScopeService(
            SourceCatalogService(db)
        )

    def create(
        self,
        configuration: AutomationConfigurationV1,
        *,
        actor: str,
        initial_state: Literal["active", "paused"] = "paused",
    ) -> AutomationProjectionV1:
        self._validate_actor(actor)
        self._validate_configuration(configuration)
        now = utc_now()
        automation = ScrapeSchedule(
            revision=1,
            lifecycle_state=initial_state,
            is_active=initial_state == "active",
            archived_at=None,
            scope_review_reason=None,
            created_at=now,
            updated_at=now,
        )
        self._apply_configuration(automation, configuration)
        try:
            self.db.add(automation)
            self.db.flush()
            snapshot = self._snapshot(automation, configuration)
            self._append_revision(
                automation,
                snapshot=snapshot,
                operation="create",
                actor=actor,
            )
            self.db.commit()
            self.db.refresh(automation)
        except Exception:
            self.db.rollback()
            raise
        self._best_effort_reconcile(automation)
        return self._projection(automation, snapshot)

    def get(self, automation_id: UUID) -> AutomationProjectionV1:
        automation = self._require_automation(automation_id)
        revision = self.repository.get_revision(
            self.db,
            automation_id=automation.id,
            revision=automation.revision,
        )
        if revision is None:
            raise RuntimeError("Automation current revision snapshot is missing")
        snapshot = AutomationSnapshotV1.model_validate(revision.snapshot)
        return self._projection(automation, snapshot)

    def list(
        self,
        *,
        source_site: str | None = None,
        lifecycle_state: AutomationLifecycleState | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[AutomationProjectionV1, ...], int]:
        rows, total = self.repository.list_with_current_revision(
            self.db,
            source_site=source_site,
            lifecycle_state=lifecycle_state,
            offset=offset,
            limit=limit,
        )
        return (
            tuple(
                self._projection(
                    automation,
                    AutomationSnapshotV1.model_validate(revision.snapshot),
                )
                for automation, revision in rows
            ),
            total,
        )

    def update_configuration(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        configuration: AutomationConfigurationV1,
        actor: str,
    ) -> AutomationProjectionV1:
        self._validate_actor(actor)
        self._validate_configuration(configuration)
        automation = self._require_automation(
            automation_id,
            for_update=True,
        )
        self._require_revision(automation, expected_revision)
        self._require_versioned(automation)

        if automation.lifecycle_state == "scope_review_required":
            automation.lifecycle_state = "paused"
        automation.scope_review_reason = None
        automation.revision += 1
        automation.updated_at = utc_now()
        automation.next_run_at = None
        self._apply_configuration(automation, configuration)
        snapshot = self._snapshot(automation, configuration)
        return self._commit_revision(
            automation,
            snapshot=snapshot,
            operation="update",
            actor=actor,
        )

    def pause(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
    ) -> AutomationProjectionV1:
        return self._transition(
            automation_id,
            expected_revision=expected_revision,
            actor=actor,
            operation="pause",
        )

    def resume(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
    ) -> AutomationProjectionV1:
        return self._transition(
            automation_id,
            expected_revision=expected_revision,
            actor=actor,
            operation="resume",
        )

    def archive(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
    ) -> AutomationProjectionV1:
        return self._transition(
            automation_id,
            expected_revision=expected_revision,
            actor=actor,
            operation="archive",
        )

    def restore(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
        activate: bool = False,
    ) -> AutomationProjectionV1:
        return self._transition(
            automation_id,
            expected_revision=expected_revision,
            actor=actor,
            operation="restore_active" if activate else "restore",
        )

    def mark_scope_review_required(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        reason: CrawlScopeErrorPayloadV1,
        actor: str,
    ) -> AutomationProjectionV1:
        self._validate_actor(actor)
        automation = self._require_automation(automation_id, for_update=True)
        self._require_revision(automation, expected_revision)
        self._require_versioned(automation)
        if automation.lifecycle_state == "archived":
            raise AutomationTransitionInvalidError(
                current_state=automation.lifecycle_state,
                operation="scope_review_required",
            )
        configuration = self._current_configuration(automation)
        automation.lifecycle_state = "scope_review_required"
        automation.is_active = False
        automation.next_run_at = None
        automation.scope_review_reason = reason.model_dump(mode="json")
        automation.revision += 1
        automation.updated_at = utc_now()
        snapshot = self._snapshot(automation, configuration)
        return self._commit_revision(
            automation,
            snapshot=snapshot,
            operation="scope_review_required",
            actor=actor,
        )

    def review_permanent_delete(
        self,
        automation_id: UUID,
        *,
        actor: str,
        ttl: timedelta = timedelta(minutes=10),
    ) -> AutomationDeleteReviewGrantV1:
        self._validate_actor(actor)
        automation = self._require_automation(automation_id, for_update=True)
        self._require_versioned(automation)
        if automation.lifecycle_state != "archived":
            raise AutomationTransitionInvalidError(
                current_state=automation.lifecycle_state,
                operation="delete_review",
            )
        impact = self.repository.delete_impact(self.db, automation)
        review_token = secrets.token_urlsafe(32)
        expires_at = utc_now() + ttl
        review = AutomationDeleteReview(
            automation_id=automation.id,
            automation_id_snapshot=automation.id,
            expected_revision=automation.revision,
            actor=actor,
            token_hash=self._token_hash(review_token),
            impact_fingerprint=impact.fingerprint,
            impact_snapshot=impact.model_dump(mode="json"),
            expires_at=expires_at,
        )
        try:
            self.db.add(review)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return AutomationDeleteReviewGrantV1(
            review_token=review_token,
            expires_at=expires_at,
            impact=impact,
        )

    def permanently_delete(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
        review_token: str,
    ) -> AutomationDeleteImpactV1:
        self._validate_actor(actor)
        automation = self._require_automation(automation_id, for_update=True)
        self._require_revision(automation, expected_revision)
        self._require_versioned(automation)
        if automation.lifecycle_state != "archived":
            raise AutomationTransitionInvalidError(
                current_state=automation.lifecycle_state,
                operation="permanent_delete",
            )
        review = self.repository.get_delete_review_for_update(
            self.db,
            token_hash=self._token_hash(review_token),
        )
        if review is None:
            raise AutomationDeleteReviewStaleError(
                "Automation delete review token is unknown"
            )
        expires_at = self._aware_utc(review.expires_at)
        if (
            review.automation_id_snapshot != automation.id
            or review.expected_revision != automation.revision
            or review.actor != actor
            or review.consumed_at is not None
            or expires_at <= utc_now()
        ):
            raise AutomationDeleteReviewStaleError(
                "Automation delete review is expired, consumed, or stale"
            )
        impact = self.repository.delete_impact(self.db, automation)
        if review.impact_fingerprint != impact.fingerprint:
            raise AutomationDeleteReviewStaleError(
                "Automation delete impact changed after review"
            )
        review.consumed_at = utc_now()
        self.db.flush()
        try:
            self.db.delete(automation)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._best_effort_remove(automation_id)
        return impact

    def _transition(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        actor: str,
        operation: Literal[
            "pause",
            "resume",
            "archive",
            "restore",
            "restore_active",
        ],
    ) -> AutomationProjectionV1:
        self._validate_actor(actor)
        automation = self._require_automation(automation_id, for_update=True)
        self._require_revision(automation, expected_revision)
        self._require_versioned(automation)
        configuration = self._current_configuration(automation)
        current_state = automation.lifecycle_state

        if operation == "pause" and current_state in {
            "active",
            "scope_review_required",
        }:
            target_state: AutomationLifecycleState = "paused"
        elif operation == "resume" and current_state == "paused":
            self._validate_configuration(configuration)
            target_state = "active"
            automation.scope_review_reason = None
        elif operation == "archive" and current_state in {
            "active",
            "paused",
            "scope_review_required",
        }:
            target_state = "archived"
        elif operation in {"restore", "restore_active"} and current_state == "archived":
            self._validate_configuration(configuration)
            target_state = "active" if operation == "restore_active" else "paused"
            automation.scope_review_reason = None
        else:
            raise AutomationTransitionInvalidError(
                current_state=current_state,
                operation=operation,
            )

        now = utc_now()
        automation.lifecycle_state = target_state
        automation.is_active = target_state == "active"
        automation.archived_at = now if target_state == "archived" else None
        automation.next_run_at = None
        automation.revision += 1
        automation.updated_at = now
        snapshot = self._snapshot(automation, configuration)
        return self._commit_revision(
            automation,
            snapshot=snapshot,
            operation=operation,
            actor=actor,
        )

    def _validate_configuration(
        self,
        configuration: AutomationConfigurationV1,
    ) -> None:
        CronTrigger.from_crontab(
            configuration.cron_expression,
            timezone=configuration.timezone,
        )
        if configuration.listing_settings is not None:
            self.scope_service.preview(
                configuration.scope,
                listing_settings=configuration.listing_settings,
            )
            return
        detail_settings = configuration.detail_settings
        assert detail_settings is not None
        self.scope_service.preview(configuration.scope)
        supported_modes = get_supported_crawl_modes(
            configuration.scope.source_site
        )
        if detail_settings.crawl_mode not in supported_modes:
            raise ScopeRuleInvalidError(
                "Crawl mode is not supported by this source",
                context={
                    "source_site": configuration.scope.source_site,
                    "crawl_mode": detail_settings.crawl_mode,
                    "supported_crawl_modes": ",".join(supported_modes),
                },
            )

    @staticmethod
    def _apply_configuration(
        automation: ScrapeSchedule,
        configuration: AutomationConfigurationV1,
    ) -> None:
        automation.name = configuration.name
        automation.description = configuration.description
        automation.cron_expression = configuration.cron_expression
        automation.timezone = configuration.timezone
        automation.source_site = configuration.scope.source_site
        automation.crawl_phase = configuration.crawl_phase
        automation.crawl_mode = configuration.crawl_mode
        automation.scope_contract = configuration.scope.model_dump(mode="json")
        if configuration.listing_settings is not None:
            automation.listing_page_depth = (
                configuration.listing_settings.page_depth
            )
            automation.listing_run_page_cap = (
                configuration.listing_settings.run_page_cap
            )
            automation.detail_run_cap = None
            automation.detail_limit_kind = None
            automation.detail_backlog_scope = None
            automation.max_pages = configuration.listing_settings.page_depth
            automation.detail_limit = 100
        else:
            detail_settings = configuration.detail_settings
            assert detail_settings is not None
            automation.listing_page_depth = None
            automation.listing_run_page_cap = None
            automation.detail_backlog_scope = (
                detail_settings.backlog_scope.model_dump(mode="json")
            )
            automation.detail_limit_kind = detail_settings.limit.kind
            automation.detail_run_cap = (
                detail_settings.limit.detail_run_cap
                if detail_settings.limit.kind == "stop_after"
                else None
            )
            automation.max_pages = 1
            automation.detail_limit = automation.detail_run_cap or 1

    def _snapshot(
        self,
        automation: ScrapeSchedule,
        configuration: AutomationConfigurationV1,
    ) -> AutomationSnapshotV1:
        return AutomationSnapshotV1(
            automation_id=automation.id,
            revision=automation.revision,
            lifecycle_state=automation.lifecycle_state,
            configuration=configuration,
            scope_review_reason=(
                CrawlScopeErrorPayloadV1.model_validate(
                    automation.scope_review_reason
                )
                if automation.scope_review_reason is not None
                else None
            ),
            archived_at=automation.archived_at,
        )

    def _append_revision(
        self,
        automation: ScrapeSchedule,
        *,
        snapshot: AutomationSnapshotV1,
        operation: str,
        actor: str,
    ) -> None:
        self.repository.append_revision(
            self.db,
            automation_id=automation.id,
            revision=automation.revision,
            snapshot=snapshot.model_dump(mode="json"),
            snapshot_fingerprint=snapshot.fingerprint,
            operation=operation,
            actor=actor,
        )

    def _commit_revision(
        self,
        automation: ScrapeSchedule,
        *,
        snapshot: AutomationSnapshotV1,
        operation: str,
        actor: str,
    ) -> AutomationProjectionV1:
        try:
            self._append_revision(
                automation,
                snapshot=snapshot,
                operation=operation,
                actor=actor,
            )
            self.db.commit()
            self.db.refresh(automation)
        except Exception:
            self.db.rollback()
            raise
        self._best_effort_reconcile(automation)
        return self._projection(automation, snapshot)

    def _current_configuration(
        self,
        automation: ScrapeSchedule,
    ) -> AutomationConfigurationV1:
        revision = self.repository.get_revision(
            self.db,
            automation_id=automation.id,
            revision=automation.revision,
        )
        if revision is None:
            raise RuntimeError("Automation current revision snapshot is missing")
        return AutomationSnapshotV1.model_validate(
            revision.snapshot
        ).configuration

    def _require_automation(
        self,
        automation_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScrapeSchedule:
        automation = self.repository.get(
            self.db,
            automation_id,
            for_update=for_update,
        )
        if automation is None:
            raise AutomationNotFoundError(automation_id)
        return automation

    @staticmethod
    def _require_versioned(automation: ScrapeSchedule) -> None:
        if automation.scope_contract is None:
            raise AutomationTransitionInvalidError(
                current_state="legacy",
                operation="versioned_automation_required",
            )

    @staticmethod
    def _require_revision(
        automation: ScrapeSchedule,
        expected_revision: int,
    ) -> None:
        if automation.revision != expected_revision:
            raise AutomationRevisionConflictError(
                automation_id=automation.id,
                expected_revision=expected_revision,
                current_revision=automation.revision,
            )

    @staticmethod
    def _validate_actor(actor: str) -> None:
        if not str(actor or "").strip():
            raise ValueError("Automation mutation actor is required")

    @staticmethod
    def _projection(
        automation: ScrapeSchedule,
        snapshot: AutomationSnapshotV1,
    ) -> AutomationProjectionV1:
        return AutomationProjectionV1(
            snapshot=snapshot,
            created_at=AutomationService._aware_utc(automation.created_at),
            updated_at=AutomationService._aware_utc(automation.updated_at),
            last_run_at=(
                AutomationService._aware_utc(automation.last_run_at)
                if automation.last_run_at is not None
                else None
            ),
            next_run_at=(
                AutomationService._aware_utc(automation.next_run_at)
                if automation.next_run_at is not None
                else None
            ),
        )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _token_hash(review_token: str) -> str:
        return hashlib.sha256(review_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _best_effort_reconcile(automation: ScrapeSchedule) -> None:
        try:
            from app.services.scheduler_service import SchedulerService

            scheduler = SchedulerService._instance
            if scheduler is not None and scheduler._initialized:
                scheduler.update_schedule(automation)
        except Exception:
            return

    @staticmethod
    def _best_effort_remove(automation_id: UUID) -> None:
        try:
            from app.services.scheduler_service import SchedulerService

            scheduler = SchedulerService._instance
            if scheduler is not None and scheduler._initialized:
                scheduler.remove_schedule(automation_id)
        except Exception:
            return
