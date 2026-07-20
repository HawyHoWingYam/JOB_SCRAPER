from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.crawl_control.automation_review_contracts import (
    AutomationDetailPreviewV1,
    AutomationReviewRequestV1,
    AutomationReviewV1,
    AutomationScheduleSummaryV1,
)
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.contracts import CrawlScopeErrorPayloadV1
from app.crawl_control.detail_runtime import DetailBacklogSnapshotBuilder
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanContentV1,
    DispatchPlanReadinessV1,
)
from app.crawl_control.errors import AutomationRevisionConflictError
from app.crawl_control.scope_service import CrawlScopeService
from app.services.source_catalog_service import SourceCatalogService
from app.source_catalog.domain import payload_fingerprint
from app.utils.time import utc_now


_PRESET_SUMMARIES = {
    "0 * * * *": "Every hour",
    "0 2 * * *": "Daily at 02:00",
    "0 4 * * *": "Daily at 04:00",
    "0 9 * * 1-5": "Weekdays at 09:00",
    "0 9 * * 1": "Mondays at 09:00",
}


def _ensure_runtime_ready(*, crawl_mode: str, source_site: str) -> None:
    from app.services.headed_crawl_runtime import (
        ensure_headed_crawl_worker_available,
    )

    ensure_headed_crawl_worker_available(
        crawl_mode=crawl_mode,
        source_site=source_site,
    )


class AutomationReviewService:
    """Build one read-only, fingerprinted Automation review projection."""

    def __init__(
        self,
        db: Session,
        *,
        scope_service: CrawlScopeService | None = None,
        automation_service: AutomationService | None = None,
        detail_backlog_builder: DetailBacklogSnapshotBuilder | None = None,
        runtime_readiness_check: Callable[..., None] = _ensure_runtime_ready,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.scope_service = scope_service or CrawlScopeService(
            SourceCatalogService(db)
        )
        self.automation_service = automation_service or AutomationService(db)
        self.detail_backlog_builder = (
            detail_backlog_builder or DetailBacklogSnapshotBuilder()
        )
        self.runtime_readiness_check = runtime_readiness_check
        self.clock = clock

    def review(self, request: AutomationReviewRequestV1) -> AutomationReviewV1:
        configuration = request.configuration
        before = None
        if request.automation_id is not None:
            before = self.automation_service.get(request.automation_id)
            assert request.expected_revision is not None
            if before.snapshot.revision != request.expected_revision:
                raise AutomationRevisionConflictError(
                    automation_id=request.automation_id,
                    expected_revision=request.expected_revision,
                    current_revision=before.snapshot.revision,
                )

        trigger = CronTrigger.from_crontab(
            configuration.cron_expression,
            timezone=configuration.timezone,
        )
        scope_preview = self.scope_service.preview(
            configuration.scope,
            listing_settings=configuration.listing_settings,
        )
        now = self.clock()
        readiness = self._readiness(configuration, now=now)
        warnings: list[CrawlScopeErrorPayloadV1] = []
        detail_preview = None

        if configuration.detail_settings is not None:
            content = DispatchPlanContentV1(
                source_site=configuration.scope.source_site,
                crawl_phase="detail",
                trigger_kind="one_off",
                catalog_revision_id=scope_preview.resolved_scope.catalog_revision_id,
                authored_scope=configuration.scope,
                resolved_scope=scope_preview.resolved_scope,
                detail_settings=configuration.detail_settings,
            )
            counts = self.detail_backlog_builder.preview(
                self.db,
                content=content,
                eligible_at_or_before=now,
            )
            limit = configuration.detail_settings.limit
            detail_preview = AutomationDetailPreviewV1(
                backlog_scope=configuration.detail_settings.backlog_scope,
                eligible_now_count=counts.eligible_target_count,
                selected_now_count=counts.selected_target_count,
                limit_kind=limit.kind,
                detail_run_cap=(
                    limit.detail_run_cap
                    if limit.kind == "stop_after"
                    else counts.absolute_safety_cap
                ),
                absolute_safety_cap=counts.absolute_safety_cap,
            )
            if counts.eligible_target_count == 0:
                warnings.append(
                    CrawlScopeErrorPayloadV1(
                        code="DETAIL_BACKLOG_EMPTY_NOW",
                        message=(
                            "No detail targets are eligible now; a future scheduled "
                            "run will take its own snapshot"
                        ),
                        context={"source_site": configuration.scope.source_site},
                    )
                )
            if counts.selected_target_count > counts.absolute_safety_cap:
                readiness = DispatchPlanReadinessV1(
                    status="blocked",
                    checked_at=now,
                    blocking_errors=(
                        CrawlScopeErrorPayloadV1(
                            code="BACKLOG_SAFETY_CAP_EXCEEDED",
                            message="Current detail preview exceeds the absolute safety cap",
                            context={
                                "selected_target_count": counts.selected_target_count,
                                "absolute_safety_cap": counts.absolute_safety_cap,
                            },
                        ),
                    ),
                    capabilities=readiness.capabilities,
                )

        schedule = self._schedule_summary(configuration, trigger=trigger, now=now)
        fingerprint = self._fingerprint(
            request=request,
            resolved_scope=scope_preview.resolved_scope,
            listing_workload=scope_preview.listing_workload,
            detail_preview=detail_preview,
            readiness=readiness,
            warnings=tuple(warnings),
            before=before,
            schedule=schedule,
        )
        return AutomationReviewV1(
            input_fingerprint=fingerprint,
            automation_id=request.automation_id,
            expected_revision=request.expected_revision,
            catalog_revision_id=scope_preview.resolved_scope.catalog_revision_id,
            authored_scope=configuration.scope,
            resolved_scope=scope_preview.resolved_scope,
            listing_workload=scope_preview.listing_workload,
            detail_preview=detail_preview,
            schedule_summary=schedule,
            readiness=readiness,
            warnings=tuple(warnings),
            before=before,
        )

    def _readiness(self, configuration, *, now: datetime) -> DispatchPlanReadinessV1:
        settings = configuration.listing_settings or configuration.detail_settings
        assert settings is not None
        blocking_errors = []
        capabilities = {
            "crawl_mode": settings.crawl_mode,
            "runtime_ready": True,
        }
        try:
            self.runtime_readiness_check(
                crawl_mode=settings.crawl_mode,
                source_site=configuration.scope.source_site,
            )
        except Exception as exc:
            from app.services.headed_crawl_runtime import (
                HeadedCrawlWorkerUnavailableError,
            )

            if not isinstance(exc, HeadedCrawlWorkerUnavailableError):
                raise
            capabilities["runtime_ready"] = False
            blocking_errors.append(
                CrawlScopeErrorPayloadV1(
                    code="HEADED_WORKER_UNAVAILABLE",
                    message=str(exc),
                    context={"source_site": configuration.scope.source_site},
                )
            )
        return DispatchPlanReadinessV1(
            status="blocked" if blocking_errors else "ready",
            checked_at=now,
            blocking_errors=tuple(blocking_errors),
            capabilities=capabilities,
        )

    @staticmethod
    def _schedule_summary(configuration, *, trigger, now) -> AutomationScheduleSummaryV1:
        timezone = ZoneInfo(configuration.timezone)
        localized_now = now.astimezone(timezone)
        next_run = trigger.get_next_fire_time(None, localized_now)
        if next_run is None:
            raise ValueError("Automation cron expression has no next run")
        summary = _PRESET_SUMMARIES.get(
            configuration.cron_expression,
            f"Custom schedule ({configuration.cron_expression})",
        )
        return AutomationScheduleSummaryV1(
            cron_expression=configuration.cron_expression,
            timezone=configuration.timezone,
            human_summary=f"{summary} · {configuration.timezone}",
            next_run_at=next_run,
        )

    @staticmethod
    def _fingerprint(
        *,
        request,
        resolved_scope,
        listing_workload,
        detail_preview,
        readiness,
        warnings,
        before,
        schedule,
    ) -> str:
        readiness_payload = readiness.model_dump(mode="json")
        readiness_payload.pop("checked_at", None)
        return payload_fingerprint(
            {
                "configuration": request.configuration.model_dump(mode="json"),
                "automation_id": (
                    str(request.automation_id) if request.automation_id else None
                ),
                "expected_revision": request.expected_revision,
                "catalog_revision_id": str(resolved_scope.catalog_revision_id),
                "resolved_scope_fingerprint": resolved_scope.fingerprint,
                "listing_workload": (
                    listing_workload.model_dump(mode="json")
                    if listing_workload is not None
                    else None
                ),
                "detail_preview": (
                    detail_preview.model_dump(mode="json")
                    if detail_preview is not None
                    else None
                ),
                "readiness": readiness_payload,
                "warnings": [item.model_dump(mode="json") for item in warnings],
                "before_fingerprint": (
                    before.snapshot.fingerprint if before is not None else None
                ),
                "schedule": {
                    "cron_expression": schedule.cron_expression,
                    "timezone": schedule.timezone,
                    "human_summary": schedule.human_summary,
                },
            }
        )
