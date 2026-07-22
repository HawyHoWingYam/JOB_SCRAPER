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
    AutomationLatestOutcomeV1,
    AutomationRowProjectionV1,
    AutomationRowProjectionV2,
    AutomationScheduleProjectionV1,
    BoardActionV1,
    BoardActiveRunV2,
    BoardAttentionItemV2,
    BoardSourceSummaryV2,
    CatalogHealthProjectionV1,
    CrawlControlRunProjectionV1,
    CrawlTaskDetailProjectionV1,
    CrawlTaskIssueProjectionV1,
    DetailSnapshotProjectionV1,
    ListingRecoveryProjectionV1,
    ListingWorkloadProjectionV1,
    ManualActionGuidanceProjectionV1,
    RecoveryAttemptProjectionV1,
    ResolvedScopeSummaryV1,
    RunAuthorityProjectionV1,
    TaskControlBoardProjectionV1,
    TaskControlBoardProjectionV2,
)
from app.crawl_control.automation_service import AutomationService
from app.crawl_cancellation import (
    CANCELLABLE_CRAWL_JOB_STATUSES,
    TERMINAL_CRAWL_JOB_STATUSES,
    can_request_cancellation,
)
from app.crawl_modes import resolve_crawl_mode
from app.crawl_phases import resolve_crawl_phase
from app.services.source_catalog import resolve_default_max_pages
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.utils.time import utc_now


SUPPORTED_BOARD_SOURCES: tuple[SourceSite, ...] = (
    "jobsdb",
    "ctgoodjobs",
    "offertoday",
)
ACTIVE_BOARD_RUN_STATUSES = frozenset(
    {*CANCELLABLE_CRAWL_JOB_STATUSES, "cancelling"}
)
_PRESET_SCHEDULES = {
    "0 * * * *": "Every hour",
    "0 2 * * *": "Daily at 02:00",
    "0 4 * * *": "Daily at 04:00",
    "0 9 * * 1-5": "Weekdays at 09:00",
    "0 9 * * 1": "Mondays at 09:00",
}


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


def _bounded_text(value: Any, *, fallback: str, limit: int = 1000) -> str:
    text = str(value or fallback).strip() or fallback
    return text[:limit]


def _issue_projection(
    normalized: Mapping[str, Any],
) -> CrawlTaskIssueProjectionV1 | None:
    issue_class = str(normalized.get("issue_class") or "").strip().lower()
    status = str(normalized.get("status") or "").strip().lower()
    if not issue_class and status not in {"failed", "manual_action_required"}:
        return None
    if not issue_class:
        issue_class = "failed_run" if status == "failed" else "manual_action_required"
    return CrawlTaskIssueProjectionV1(
        issue_class=issue_class[:100],
        code=(str(normalized.get("issue_code"))[:100] if normalized.get("issue_code") else None),
        stage=(str(normalized.get("issue_stage"))[:100] if normalized.get("issue_stage") else None),
        summary=_bounded_text(
            normalized.get("latest_issue_text") or normalized.get("error"),
            fallback="This run needs operator attention.",
        ),
    )


def _manual_action_guidance(
    normalized: Mapping[str, Any],
) -> ManualActionGuidanceProjectionV1 | None:
    raw = normalized.get("manual_action")
    if not isinstance(raw, Mapping):
        return None
    source_site = str(raw.get("source_site") or normalized.get("source_site") or "").strip().lower()
    if source_site not in SUPPORTED_BOARD_SOURCES:
        return None
    instructions_value = raw.get("instructions")
    if isinstance(instructions_value, str):
        instructions = (instructions_value[:500],)
    elif isinstance(instructions_value, (list, tuple)):
        instructions = tuple(
            _bounded_text(item, fallback="Continue in the supported operator flow.", limit=500)
            for item in instructions_value[:10]
            if str(item or "").strip()
        )
    else:
        instructions = ()
    resume_supported = bool(raw.get("resume_supported"))
    strategies: list[str] = []
    # The normalized manual-action contract defines fresh-profile as the
    # baseline resume path; only browser reuse is an optional capability.
    if resume_supported:
        strategies.append("fresh_profile")
    if bool(raw.get("reuse_open_browser_supported")):
        strategies.append("reuse_open_browser")
    return ManualActionGuidanceProjectionV1(
        source_site=source_site,
        action_type=(str(raw.get("action_type"))[:100] if raw.get("action_type") else None),
        classification=(str(raw.get("classification"))[:100] if raw.get("classification") else None),
        stage=(str(raw.get("stage"))[:100] if raw.get("stage") else None),
        code=(str(raw.get("code"))[:100] if raw.get("code") else None),
        message=_bounded_text(
            raw.get("message") or raw.get("reason") or normalized.get("latest_issue_text"),
            fallback="Complete the supported manual action before resuming.",
        ),
        instructions=instructions,
        resume_supported=resume_supported,
        resume_strategies=tuple(strategies) if resume_supported else (),
        worker_ready=(bool(raw.get("worker_ready")) if raw.get("worker_ready") is not None else None),
    )


def _run_actions(crawl_job, normalized: Mapping[str, Any]) -> tuple[BoardActionV1, ...]:
    status = str(normalized.get("status") or crawl_job.status).strip().lower()
    manual = _manual_action_guidance(normalized)
    cancel_enabled = can_request_cancellation(
        trigger_type=crawl_job.trigger_type,
        status=status,
        schedule_id=crawl_job.schedule_id,
    )
    resume_enabled = bool(
        status == "manual_action_required"
        and manual is not None
        and manual.resume_supported
    )
    return (
        BoardActionV1(action="view_task", enabled=True),
        BoardActionV1(action="view_logs", enabled=True),
        BoardActionV1(
            action="cancel",
            enabled=cancel_enabled,
            reason_code=None if cancel_enabled else "RUN_NOT_CANCELLABLE",
        ),
        BoardActionV1(
            action="resume_manual_action",
            enabled=resume_enabled,
            reason_code=None if resume_enabled else "MANUAL_RESUME_UNAVAILABLE",
        ),
    )


def _listing_recovery(
    *,
    crawl_job,
    normalized: Mapping[str, Any],
    run: CrawlControlRunProjectionV1,
) -> ListingRecoveryProjectionV1 | None:
    status = str(normalized.get("status") or crawl_job.status).strip().lower()
    if (
        status != "completed"
        or run.crawl_phase != "listing"
        or run.listing_workload is None
    ):
        return None

    raw_ids = normalized.get("listing_capped_classification_ids")
    if isinstance(raw_ids, set):
        raw_ids = sorted(raw_ids, key=lambda item: str(item))
    capped_ids = (
        tuple(str(item).strip() for item in raw_ids if str(item).strip())
        if isinstance(raw_ids, (list, tuple, set))
        else ()
    )
    listing_partial = bool(normalized.get("listing_partial"))
    if not listing_partial:
        return None
    capped_count = max(
        _to_int(normalized.get("listing_capped_condition_count")),
        len(capped_ids),
    )
    source_site = str(crawl_job.source_site or "").strip().lower()
    source_prefix = f"{source_site}:"
    ids_are_source_qualified = bool(capped_ids) and all(
        item.lower().startswith(source_prefix) for item in capped_ids
    )
    return ListingRecoveryProjectionV1(
        listing_partial=listing_partial,
        query_target_count=run.listing_workload.query_target_count,
        capped_query_target_count=min(
            capped_count,
            run.listing_workload.query_target_count,
        ),
        page_depth=run.listing_workload.page_depth,
        pages_requested=run.listing_workload.pages_requested,
        capped_classification_ids=capped_ids,
        continuation_supported=bool(
            listing_partial
            and capped_ids
            and ids_are_source_qualified
            and source_site in {"offertoday", "jobsdb", "ctgoodjobs"}
        ),
    )


def build_crawl_task_detail_projection(
    crawl_job,
    *,
    normalized: Mapping[str, Any],
) -> CrawlTaskDetailProjectionV1:
    run = build_crawl_control_run_projection(crawl_job, normalized=normalized)
    return CrawlTaskDetailProjectionV1(
        run=run,
        persisted_status=str(normalized.get("persisted_status") or crawl_job.status),
        operator_state=(str(normalized.get("operator_state"))[:100] if normalized.get("operator_state") else None),
        queued_at=_aware_utc(crawl_job.queued_at),
        started_at=(_aware_utc(crawl_job.started_at) if crawl_job.started_at else None),
        completed_at=(_aware_utc(crawl_job.completed_at) if crawl_job.completed_at else None),
        updated_at=_aware_utc(crawl_job.updated_at),
        detail_pacing=(dict(normalized["detail_pacing"]) if isinstance(normalized.get("detail_pacing"), Mapping) else None),
        listing_recovery=_listing_recovery(
            crawl_job=crawl_job,
            normalized=normalized,
            run=run,
        ),
        issue=_issue_projection(normalized),
        manual_action_guidance=_manual_action_guidance(normalized),
        recovery_attempt=run.recovery_attempt,
        actions=_run_actions(crawl_job, normalized),
    )


def _automation_actions(projection) -> tuple[BoardActionV1, ...]:
    state = projection.snapshot.lifecycle_state
    return (
        BoardActionV1(action="edit", enabled=state != "archived", reason_code="AUTOMATION_ARCHIVED" if state == "archived" else None),
        BoardActionV1(action="run_now", enabled=state in {"active", "paused"}, reason_code=None if state in {"active", "paused"} else "AUTOMATION_NOT_RUNNABLE"),
        BoardActionV1(action="pause", enabled=state == "active", reason_code=None if state == "active" else "AUTOMATION_NOT_ACTIVE"),
        BoardActionV1(action="resume", enabled=state == "paused", reason_code=None if state == "paused" else "AUTOMATION_NOT_PAUSED"),
        BoardActionV1(action="archive", enabled=state != "archived", reason_code=None if state != "archived" else "AUTOMATION_ARCHIVED"),
        BoardActionV1(action="restore", enabled=state == "archived", reason_code=None if state == "archived" else "AUTOMATION_NOT_ARCHIVED"),
        BoardActionV1(action="delete_review", enabled=state == "archived", reason_code=None if state == "archived" else "AUTOMATION_NOT_ARCHIVED"),
        BoardActionV1(action="view_logs", enabled=True),
    )


def _catalog_health(revision, *, source_site: SourceSite) -> CatalogHealthProjectionV1:
    if revision is None:
        return CatalogHealthProjectionV1(source_site=source_site, state="unpublished")
    return CatalogHealthProjectionV1(
        source_site=source_site,
        state="healthy",
        revision_id=revision.id,
        sequence=revision.sequence,
        fingerprint=revision.fingerprint,
        published_at=_aware_utc(revision.published_at),
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

    def get_v2(
        self,
        *,
        selected_source: SourceSite,
        run_limit: int = 100,
    ) -> TaskControlBoardProjectionV2:
        automation_service = AutomationService(self.db)
        automation_projections = []
        rows = []
        for source in SUPPORTED_BOARD_SOURCES:
            source_automations, _automation_total = automation_service.list(
                source_site=source,
                limit=100,
            )
            automation_projections.extend(source_automations)
            source_rows, _run_total = self.crawl_job_repository.list_crawl_task_page(
                self.db,
                page=1,
                page_size=run_limit,
                status=None,
                source_site=source,
                crawl_mode=None,
                updated_since=None,
            )
            rows.extend(source_rows)
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
        run_entries = []
        for row in rows:
            normalized = build_crawl_task_snapshot(
                row,
                latest_event=latest_events.get(row.id),
                now=now,
                events=events.get(row.id, []),
                category_lookup_cache=category_lookup_cache,
            )
            run_entries.append(
                (
                    row,
                    normalized,
                    build_crawl_control_run_projection(row, normalized=normalized),
                )
            )

        active_revisions = {
            revision.source_site: revision
            for revision in SourceCatalogRepository().list_active_revisions(self.db)
        }
        catalog_health = {
            source: _catalog_health(active_revisions.get(source), source_site=source)
            for source in SUPPORTED_BOARD_SOURCES
        }
        active_by_automation = {}
        latest_by_automation = {}
        for _row, normalized, run in run_entries:
            automation_id = run.authority.automation_id
            if automation_id is None:
                continue
            if run.status in ACTIVE_BOARD_RUN_STATUSES and automation_id not in active_by_automation:
                active_by_automation[automation_id] = run
            if run.status in TERMINAL_CRAWL_JOB_STATUSES and automation_id not in latest_by_automation:
                latest_by_automation[automation_id] = (run, _issue_projection(normalized))

        automation_rows: list[AutomationRowProjectionV2] = []
        for projection in automation_projections:
            snapshot = projection.snapshot
            configuration = snapshot.configuration
            health = catalog_health[configuration.scope.source_site]
            if (
                health.revision_id is not None
                and health.revision_id != configuration.scope.reviewed_catalog_revision_id
            ):
                health = health.model_copy(update={"state": "stale"})
            current_run = active_by_automation.get(snapshot.automation_id)
            resolved_summary = None
            if current_run is not None and current_run.authority.resolved_scope is not None:
                resolved = current_run.authority.resolved_scope
                resolved_summary = ResolvedScopeSummaryV1(
                    catalog_revision_id=resolved.catalog_revision_id,
                    selected_classification_count=len(resolved.selected_classifications),
                    query_target_count=resolved.query_target_count,
                )
            latest = latest_by_automation.get(snapshot.automation_id)
            latest_outcome = (
                AutomationLatestOutcomeV1(
                    crawl_job_id=latest[0].crawl_job_id,
                    status=latest[0].status,
                    completed_at=latest[0].completed_at,
                    issue=latest[1],
                )
                if latest is not None
                else None
            )
            summary = _PRESET_SCHEDULES.get(
                configuration.cron_expression,
                f"Custom schedule ({configuration.cron_expression})",
            )
            automation_rows.append(
                AutomationRowProjectionV2(
                    automation_id=snapshot.automation_id,
                    revision=snapshot.revision,
                    lifecycle_state=snapshot.lifecycle_state,
                    name=configuration.name,
                    source_site=configuration.scope.source_site,
                    crawl_phase=configuration.crawl_phase,
                    crawl_mode=configuration.crawl_mode,
                    authored_scope=configuration.scope,
                    schedule=AutomationScheduleProjectionV1(
                        cron_expression=configuration.cron_expression,
                        timezone=configuration.timezone,
                        human_summary=f"{summary} · {configuration.timezone}",
                        next_run_at=projection.next_run_at,
                    ),
                    latest_outcome=latest_outcome,
                    catalog_health=health,
                    resolved_scope_summary=resolved_summary,
                    current_run=current_run,
                    scope_review_reason=snapshot.scope_review_reason,
                    actions=_automation_actions(projection),
                    created_at=projection.created_at,
                    updated_at=projection.updated_at,
                    last_run_at=projection.last_run_at,
                )
            )

        active_runs_by_source: dict[str, list[BoardActiveRunV2]] = {
            source: [] for source in SUPPORTED_BOARD_SOURCES
        }
        attention_by_source: dict[str, list[BoardAttentionItemV2]] = {
            source: [] for source in SUPPORTED_BOARD_SOURCES
        }
        for row, normalized, run in run_entries:
            issue = _issue_projection(normalized)
            guidance = _manual_action_guidance(normalized)
            actions = _run_actions(row, normalized)
            if run.status in ACTIVE_BOARD_RUN_STATUSES:
                active_runs_by_source[run.source_site].append(
                    BoardActiveRunV2(
                        run=run,
                        issue=issue,
                        manual_action_guidance=guidance,
                        actions=actions,
                    )
                )
            attention = self._run_attention(run, issue=issue, actions=actions)
            if attention is not None:
                attention_by_source[run.source_site].append(attention)

        for source in SUPPORTED_BOARD_SOURCES:
            health = catalog_health[source]
            if health.state == "unpublished":
                attention_by_source[source].append(
                    BoardAttentionItemV2(
                        item_id=f"catalog:{source}",
                        kind="catalog_unpublished",
                        priority=0,
                        source_site=source,
                        code="CATALOG_NOT_PUBLISHED",
                        title="Source Catalog is not published",
                        summary="Execution remains blocked until a validated Source Catalog revision is published.",
                        entity_kind="catalog",
                        entity_id=source,
                        primary_action=BoardActionV1(action="open_catalog", enabled=True),
                    )
                )

        for automation in automation_rows:
            if automation.lifecycle_state == "scope_review_required":
                attention_by_source[automation.source_site].append(
                    BoardAttentionItemV2(
                        item_id=f"automation:{automation.automation_id}:scope",
                        kind="scope_review_required",
                        priority=20,
                        source_site=automation.source_site,
                        code=(automation.scope_review_reason.code if automation.scope_review_reason else "SCOPE_REVIEW_REQUIRED"),
                        title=f"{automation.name} needs scope review",
                        summary=(automation.scope_review_reason.message if automation.scope_review_reason else "Review this Automation against the current Source Catalog."),
                        entity_kind="automation",
                        entity_id=str(automation.automation_id),
                        primary_action=BoardActionV1(action="edit", enabled=True),
                        secondary_actions=(BoardActionV1(action="open_catalog", enabled=True),),
                    )
                )
            elif automation.catalog_health.state == "stale":
                attention_by_source[automation.source_site].append(
                    BoardAttentionItemV2(
                        item_id=f"automation:{automation.automation_id}:catalog",
                        kind="catalog_stale",
                        priority=30,
                        source_site=automation.source_site,
                        code="AUTOMATION_CATALOG_STALE",
                        title=f"{automation.name} uses an older Catalog revision",
                        summary="Review the Source scope before the next dispatch.",
                        entity_kind="automation",
                        entity_id=str(automation.automation_id),
                        primary_action=BoardActionV1(action="edit", enabled=True),
                        secondary_actions=(BoardActionV1(action="open_catalog", enabled=True),),
                    )
                )

        upcoming_by_source = {
            source: [
                row
                for row in automation_rows
                if row.source_site == source and row.lifecycle_state != "archived"
            ]
            for source in SUPPORTED_BOARD_SOURCES
        }
        archived_by_source = {
            source: [
                row
                for row in automation_rows
                if row.source_site == source and row.lifecycle_state == "archived"
            ]
            for source in SUPPORTED_BOARD_SOURCES
        }
        for items in attention_by_source.values():
            items.sort(key=lambda item: (item.priority, item.item_id))

        source_summaries = tuple(
            BoardSourceSummaryV2(
                source_site=source,
                state=(
                    "attention"
                    if attention_by_source[source]
                    else "running"
                    if active_runs_by_source[source]
                    else "all_clear"
                ),
                attention_count=len(attention_by_source[source]),
                active_run_count=len(active_runs_by_source[source]),
                upcoming_count=len(upcoming_by_source[source]),
                catalog_health=catalog_health[source],
            )
            for source in SUPPORTED_BOARD_SOURCES
        )
        selected_attention = tuple(attention_by_source[selected_source])
        selected_active = tuple(active_runs_by_source[selected_source])
        selected_upcoming = tuple(upcoming_by_source[selected_source])
        return TaskControlBoardProjectionV2(
            selected_source=selected_source,
            source_summaries=source_summaries,
            needs_attention=selected_attention,
            active_runs=selected_active,
            upcoming=selected_upcoming,
            archived_automations=tuple(archived_by_source[selected_source]),
            all_clear=not (selected_attention or selected_active or selected_upcoming),
            refreshed_at=now,
        )

    @staticmethod
    def _run_attention(
        run: CrawlControlRunProjectionV1,
        *,
        issue: CrawlTaskIssueProjectionV1 | None,
        actions: tuple[BoardActionV1, ...],
    ) -> BoardAttentionItemV2 | None:
        action_by_kind = {action.action: action for action in actions}
        if run.status == "manual_action_required":
            kind = "manual_action"
            priority = 10
            code = issue.code if issue and issue.code else "MANUAL_ACTION_REQUIRED"
            title = "Manual action required"
            summary = issue.summary if issue else "Complete the supported manual action before resuming."
            primary = action_by_kind["resume_manual_action"]
        elif run.status == "cancelling":
            kind = "cancelling"
            priority = 15
            code = "CANCELLATION_PENDING"
            title = "Cancellation is still being acknowledged"
            summary = "Committed work remains visible while the worker reaches a terminal acknowledgement."
            primary = action_by_kind["view_task"]
        elif run.status == "failed":
            kind = "failed_run"
            priority = 40
            code = issue.code if issue and issue.code else "RUN_FAILED"
            title = "Run failed"
            summary = issue.summary if issue else "Open Task Details for the normalized failure state."
            primary = action_by_kind["view_task"]
        else:
            return None
        return BoardAttentionItemV2(
            item_id=f"run:{run.crawl_job_id}:{kind}",
            kind=kind,
            priority=priority,
            source_site=run.source_site,
            code=code,
            title=title,
            summary=summary,
            entity_kind="run",
            entity_id=str(run.crawl_job_id),
            primary_action=primary,
            secondary_actions=(
                action_by_kind["view_task"],
                action_by_kind["view_logs"],
            ),
        )
