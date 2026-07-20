from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.crawl_control.contracts import (
    DetailSettingsV1,
    ListingSettingsV1,
    ResolvedRunScopeV1,
    SourceSite,
)
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanContentV1,
    DispatchPlanReadinessV1,
    DispatchPlanSnapshotV1,
)
from app.crawl_control.errors import DispatchPlanFingerprintMismatchError
from app.crawl_control.task_control_board_contracts import (
    AutomationRowProjectionV1,
    CrawlControlRunProjectionV1,
    DetailSnapshotProjectionV1,
    ListingWorkloadProjectionV1,
    RecoveryAttemptProjectionV1,
    RunAuthorityProjectionV1,
    TaskControlBoardProjectionV1,
)
from app.crawl_control.automation_service import AutomationService
from app.crawl_modes import resolve_crawl_mode
from app.crawl_phases import resolve_crawl_phase
from app.services.source_catalog import resolve_default_max_pages
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.utils.time import utc_now


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _plan_content_from_record(plan) -> DispatchPlanContentV1:
    return DispatchPlanContentV1(
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


def _pages_requested(crawl_job, normalized: Mapping[str, Any]) -> int:
    metrics = crawl_job.metrics if isinstance(crawl_job.metrics, dict) else {}
    persisted_runs = getattr(crawl_job, "crawl_runs", None) or ()
    run_total = sum(_to_int(run.pages_processed) for run in persisted_runs)
    return max(
        run_total,
        _to_int(normalized.get("listing_pages_requested")),
        _to_int(metrics.get("listing_pages_requested")),
        _to_int(metrics.get("pages_requested")),
        _to_int(metrics.get("pages_processed")),
    )


def _listing_workload(
    crawl_job,
    settings: ListingSettingsV1,
    resolved_scope: ResolvedRunScopeV1,
    normalized: Mapping[str, Any],
) -> ListingWorkloadProjectionV1:
    target_count = resolved_scope.query_target_count
    return ListingWorkloadProjectionV1(
        query_target_count=target_count,
        page_depth=settings.page_depth,
        estimated_max_pages=target_count * settings.page_depth,
        run_page_cap=settings.run_page_cap,
        pages_requested=_pages_requested(crawl_job, normalized),
    )


def _detail_snapshot(
    *,
    settings: DetailSettingsV1,
    plan_target_count: int,
    normalized: Mapping[str, Any],
) -> DetailSnapshotProjectionV1:
    frozen = settings.backlog_snapshot
    target_count = (
        frozen.selected_target_count
        if frozen is not None
        else _to_int(plan_target_count)
    )
    detail_run_cap = (
        settings.limit.detail_run_cap
        if settings.limit.kind == "stop_after"
        else target_count
    )
    return DetailSnapshotProjectionV1(
        backlog_scope=settings.backlog_scope.model_dump(mode="json"),
        limit_kind=settings.limit.kind,
        cutoff_at=frozen.cutoff_at if frozen is not None else None,
        target_count=target_count,
        fetched_count=_to_int(normalized.get("detail_fetched_count")),
        saved_count=_to_int(normalized.get("detail_saved_count")),
        failed_count=_to_int(normalized.get("detail_failed_count")),
        unavailable_count=_to_int(
            normalized.get("detail_unavailable_count")
        ),
        manual_action_count=_to_int(
            normalized.get("detail_manual_action_count")
        ),
        remaining_count=_to_int(normalized.get("detail_remaining_count")),
        future_eligible_count=_to_int(
            normalized.get("detail_live_future_eligible_count")
        ),
        detail_run_cap=detail_run_cap,
    )


def _legacy_projection(
    crawl_job,
    normalized: Mapping[str, Any],
) -> tuple[
    str,
    str,
    RunAuthorityProjectionV1,
    ListingWorkloadProjectionV1 | None,
    DetailSnapshotProjectionV1 | None,
]:
    payload = (
        crawl_job.request_payload
        if isinstance(crawl_job.request_payload, dict)
        else {}
    )
    crawl_phase = resolve_crawl_phase(
        normalized.get("crawl_phase") or payload.get("crawl_phase")
    )
    crawl_mode = resolve_crawl_mode(
        crawl_job.source_site,
        normalized.get("crawl_mode") or payload.get("crawl_mode"),
    )
    authority = RunAuthorityProjectionV1(authority_kind="legacy")
    if crawl_phase == "listing":
        category_ids = payload.get("category_ids")
        target_count = (
            max(len(category_ids), 1)
            if isinstance(category_ids, list)
            else 1
        )
        page_depth = max(
            _to_int(payload.get("max_pages")),
            resolve_default_max_pages(crawl_job.source_site),
        )
        workload = ListingWorkloadProjectionV1(
            query_target_count=target_count,
            page_depth=page_depth,
            estimated_max_pages=target_count * page_depth,
            run_page_cap=target_count * page_depth,
            pages_requested=_pages_requested(crawl_job, normalized),
        )
        return crawl_phase, crawl_mode, authority, workload, None

    source_listing_id = payload.get("source_listing_crawl_job_id")
    backlog_scope = (
        {
            "kind": "listing_batch",
            "source_listing_crawl_job_id": str(source_listing_id),
        }
        if source_listing_id
        else {"kind": "source_backlog"}
    )
    target_count = _to_int(normalized.get("detail_target_count"))
    detail_run_cap = max(
        _to_int(normalized.get("detail_run_cap")),
        _to_int(payload.get("detail_limit")),
        1,
    )
    detail = DetailSnapshotProjectionV1(
        backlog_scope=backlog_scope,
        limit_kind="legacy",
        cutoff_at=None,
        target_count=target_count,
        fetched_count=_to_int(normalized.get("detail_fetched_count")),
        saved_count=_to_int(normalized.get("detail_saved_count")),
        failed_count=_to_int(normalized.get("detail_failed_count")),
        unavailable_count=_to_int(
            normalized.get("detail_unavailable_count")
        ),
        manual_action_count=_to_int(
            normalized.get("detail_manual_action_count")
        ),
        remaining_count=_to_int(normalized.get("detail_remaining_count")),
        future_eligible_count=_to_int(
            normalized.get("detail_live_future_eligible_count")
        ),
        detail_run_cap=detail_run_cap,
    )
    return crawl_phase, crawl_mode, authority, None, detail


def build_crawl_control_run_projection(
    crawl_job,
    *,
    normalized: Mapping[str, Any] | None = None,
    dispatch_plan_snapshot: DispatchPlanSnapshotV1 | None = None,
) -> CrawlControlRunProjectionV1:
    values: Mapping[str, Any] = normalized or {}
    plan_record = getattr(crawl_job, "dispatch_plan", None)
    if dispatch_plan_snapshot is not None:
        content = dispatch_plan_snapshot.content
        readiness = dispatch_plan_snapshot.readiness
        plan_id = dispatch_plan_snapshot.plan_id
        fingerprint = dispatch_plan_snapshot.plan_fingerprint
        plan_state = dispatch_plan_snapshot.state
        plan_target_count = dispatch_plan_snapshot.detail_target_count
    elif plan_record is not None:
        content = _plan_content_from_record(plan_record)
        readiness = DispatchPlanReadinessV1.model_validate(plan_record.readiness)
        plan_id = plan_record.id
        fingerprint = plan_record.plan_fingerprint
        plan_state = plan_record.state
        plan_target_count = int(plan_record.detail_target_count or 0)
    else:
        content = None

    if content is not None:
        if (
            crawl_job.dispatch_plan_id != plan_id
            or crawl_job.dispatch_plan_fingerprint != fingerprint
        ):
            raise DispatchPlanFingerprintMismatchError(
                plan_id=plan_id,
                crawl_job_id=crawl_job.id,
            )
        authority = RunAuthorityProjectionV1(
            authority_kind="dispatch_plan",
            dispatch_plan_id=plan_id,
            dispatch_plan_fingerprint=fingerprint,
            plan_state=plan_state,
            catalog_revision_id=content.catalog_revision_id,
            automation_id=content.automation_id,
            automation_revision=content.expected_automation_revision,
            authored_scope=content.authored_scope,
            resolved_scope=content.resolved_scope,
            readiness=readiness,
        )
        crawl_phase = content.crawl_phase
        settings = content.listing_settings or content.detail_settings
        assert settings is not None
        crawl_mode = settings.crawl_mode
        listing_workload = (
            _listing_workload(
                crawl_job,
                content.listing_settings,
                content.resolved_scope,
                values,
            )
            if content.listing_settings is not None
            else None
        )
        detail_snapshot = (
            _detail_snapshot(
                settings=content.detail_settings,
                plan_target_count=plan_target_count,
                normalized=values,
            )
            if content.detail_settings is not None
            else None
        )
        trigger_kind = content.trigger_kind
    else:
        (
            crawl_phase,
            crawl_mode,
            authority,
            listing_workload,
            detail_snapshot,
        ) = _legacy_projection(crawl_job, values)
        trigger_kind = str(crawl_job.trigger_type or "legacy")

    return CrawlControlRunProjectionV1(
        crawl_job_id=crawl_job.id,
        source_site=crawl_job.source_site,
        crawl_phase=crawl_phase,
        crawl_mode=crawl_mode,
        trigger_kind=trigger_kind,
        status=str(values.get("status") or crawl_job.status),
        queued_at=_aware_utc(crawl_job.queued_at),
        started_at=(
            _aware_utc(crawl_job.started_at)
            if crawl_job.started_at is not None
            else None
        ),
        completed_at=(
            _aware_utc(crawl_job.completed_at)
            if crawl_job.completed_at is not None
            else None
        ),
        updated_at=_aware_utc(crawl_job.updated_at),
        authority=authority,
        listing_workload=listing_workload,
        detail_snapshot=detail_snapshot,
        recovery_attempt=(
            RecoveryAttemptProjectionV1.model_validate(
                values["recovery_attempt"]
            )
            if isinstance(values.get("recovery_attempt"), Mapping)
            else None
        ),
    )


class TaskControlBoardProjectionService:
    """Build one normalized Automation/run board without exposing raw payloads."""

    def __init__(
        self,
        db,
        *,
        crawl_job_repository: CrawlJobRepository | None = None,
    ) -> None:
        self.db = db
        self.crawl_job_repository = (
            crawl_job_repository or CrawlJobRepository()
        )

    def get(
        self,
        *,
        source_site: SourceSite | None = None,
        run_limit: int = 100,
    ) -> TaskControlBoardProjectionV1:
        automation_projections, automation_total = AutomationService(
            self.db
        ).list(
            source_site=source_site,
            limit=100,
        )
        rows, run_total = self.crawl_job_repository.list_crawl_task_page(
            self.db,
            page=1,
            page_size=run_limit,
            status=None,
            source_site=source_site,
            crawl_mode=None,
            updated_since=None,
        )
        crawl_job_ids = [row.id for row in rows]
        latest_events = self.crawl_job_repository.list_latest_events_for_jobs(
            self.db,
            crawl_job_ids=crawl_job_ids,
        )
        from app.services.crawl_task_snapshot_service import (
            PROGRESS_CONTEXT_EVENT_TYPES,
            build_crawl_task_snapshot,
        )

        events = self.crawl_job_repository.list_events_by_job_ids(
            self.db,
            crawl_job_ids=crawl_job_ids,
            event_types=PROGRESS_CONTEXT_EVENT_TYPES,
        )
        now = utc_now()
        category_lookup_cache: dict[str, dict[str, str]] = {}
        runs = tuple(
            build_crawl_control_run_projection(
                row,
                normalized=build_crawl_task_snapshot(
                    row,
                    latest_event=latest_events.get(row.id),
                    now=now,
                    events=events.get(row.id, []),
                    category_lookup_cache=category_lookup_cache,
                ),
            )
            for row in rows
        )
        return TaskControlBoardProjectionV1(
            source_site=source_site,
            automations=tuple(
                AutomationRowProjectionV1.from_projection(projection)
                for projection in automation_projections
            ),
            automation_total=automation_total,
            runs=runs,
            run_total=run_total,
            refreshed_at=now,
        )
