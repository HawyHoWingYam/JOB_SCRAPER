"""
Progress API Routes - SSE endpoint for real-time scraping progress.
"""
import asyncio
from datetime import timedelta
import json
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.database import SessionLocal
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.source_category_registry import get_source_category_registry
from app.utils.time import utc_now
from app.crawl_modes import resolve_crawl_mode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scrape", tags=["progress"])
repository = CrawlJobRepository()
TERMINAL_CRAWL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_CRAWL_JOB_STATUSES = {"queued", "running", "dispatching"}
ACTIONABLE_CRAWL_JOB_STATUSES = {"manual_action_required"}
RECENT_TERMINAL_WINDOW = timedelta(seconds=60)
BACKLOG_VISIBLE_WINDOW = timedelta(minutes=30)
ACTIVE_WORK_EVENT_TYPES = {"crawl.started"}
INACTIVE_WORK_EVENT_TYPES = {
    "crawl.manual_action_required",
    "crawl.completed",
    "crawl.failed",
    "crawl.cancelled",
}
ACTIVITY_INTERVAL_EVENT_TYPES = ACTIVE_WORK_EVENT_TYPES | INACTIVE_WORK_EVENT_TYPES


def _elapsed_seconds(reference_time, timestamp) -> int:
    if timestamp is None:
        return 0

    effective_reference = reference_time
    effective_timestamp = timestamp
    if effective_reference.tzinfo is not None and effective_timestamp.tzinfo is None:
        effective_timestamp = effective_timestamp.replace(tzinfo=effective_reference.tzinfo)
    elif effective_reference.tzinfo is None and effective_timestamp.tzinfo is not None:
        effective_reference = effective_reference.replace(tzinfo=effective_timestamp.tzinfo)

    try:
        return int((effective_reference - effective_timestamp).total_seconds())
    except TypeError:
        return 0


def _resolve_category_label(*, source_site: str, category_ids: list[Any]) -> str | None:
    if not category_ids:
        return None

    try:
        categories = get_source_category_registry().list_categories(source_site=source_site)
    except Exception:
        return None

    lookup = {
        str(category.get("id")): str(category.get("name"))
        for category in categories
        if isinstance(category, dict) and category.get("id") and category.get("name")
    }
    resolved = [lookup.get(str(category_id), str(category_id)) for category_id in category_ids[:3]]
    if not resolved:
        return None
    if len(category_ids) > 3:
        return f"{', '.join(resolved)}, +{len(category_ids) - 3}"
    return ", ".join(resolved)


def _fallback_elapsed_seconds(crawl_job, *, now) -> int:
    if crawl_job.status == "running":
        return _elapsed_seconds(now, crawl_job.started_at or crawl_job.queued_at)

    if crawl_job.status in TERMINAL_CRAWL_JOB_STATUSES:
        return _elapsed_seconds(
            crawl_job.completed_at or crawl_job.updated_at or now,
            crawl_job.started_at or crawl_job.queued_at,
        )

    if crawl_job.status == "manual_action_required":
        return _elapsed_seconds(
            crawl_job.updated_at or now,
            crawl_job.started_at or crawl_job.queued_at,
        )

    return 0


def _calculate_active_elapsed_seconds(crawl_job, *, events: list[Any], now) -> int:
    total_seconds = 0
    active_started_at = None
    saw_active_interval = False

    for event in events:
        event_type = getattr(event, "event_type", None)
        created_at = getattr(event, "created_at", None)
        if created_at is None:
            continue

        if event_type in ACTIVE_WORK_EVENT_TYPES:
            active_started_at = created_at
            saw_active_interval = True
            continue

        if active_started_at is None:
            continue

        if event_type in INACTIVE_WORK_EVENT_TYPES:
            total_seconds += max(0, _elapsed_seconds(created_at, active_started_at))
            active_started_at = None

    if active_started_at is not None and crawl_job.status == "running":
        total_seconds += max(0, _elapsed_seconds(now, active_started_at))

    if saw_active_interval:
        return total_seconds

    return _fallback_elapsed_seconds(crawl_job, now=now)


def _build_progress_snapshot(crawl_job, latest_event, *, now, events: list[Any] | None = None) -> dict[str, Any]:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    request_payload = event_payload.get("request_payload") or crawl_job.request_payload or {}
    category_ids = list(event_payload.get("category_ids") or request_payload.get("category_ids") or [])
    category_label = event_payload.get("category_name")
    if not category_label:
        category_label = _resolve_category_label(
            source_site=crawl_job.source_site,
            category_ids=category_ids,
        )
    if not category_label:
        if category_ids:
            category_label = ", ".join(str(category_id) for category_id in category_ids[:3])
            if len(category_ids) > 3:
                category_label = f"{category_label}, +{len(category_ids) - 3}"
        else:
            category_label = f"{crawl_job.source_site} crawl"

    metrics = crawl_job.metrics if isinstance(crawl_job.metrics, dict) else {}
    job_ids_collected = _to_int(event_payload.get("job_ids_collected", metrics.get("job_ids_collected", 0)))
    jobs_scraped = _to_int(event_payload.get("jobs_scraped", metrics.get("items_emitted", 0)))
    jobs_saved = _to_int(event_payload.get("jobs_saved", metrics.get("ingest_items_seen", 0)))
    save_total = _to_int(
        event_payload.get(
            "save_total",
            metrics.get("save_total", metrics.get("items_emitted", 0)),
        )
    )
    total_jobs = _to_int(event_payload.get("total_jobs", max(job_ids_collected, jobs_scraped)))
    listings_staged = _to_int(event_payload.get("listings_staged", metrics.get("listings_staged", 0)))
    jobs_skipped_existing = _to_int(
        event_payload.get("jobs_skipped_existing", metrics.get("jobs_skipped_existing", 0))
    )
    detail_selected_rows = _to_int(
        event_payload.get("detail_selected_rows", metrics.get("detail_selected_rows", 0))
    )
    detail_skipped_existing_rows = _to_int(
        event_payload.get(
            "detail_skipped_existing_rows",
            metrics.get("detail_skipped_existing_rows", 0),
        )
    )
    detail_target_rows = _to_int(
        event_payload.get("detail_target_rows", metrics.get("detail_target_rows", total_jobs))
    )
    detail_pending = _to_int(event_payload.get("detail_pending", metrics.get("detail_pending", 0)))
    detail_running = _to_int(event_payload.get("detail_running", metrics.get("detail_running", 0)))
    detail_completed = _to_int(event_payload.get("detail_completed", metrics.get("detail_completed", 0)))
    detail_failed = _to_int(event_payload.get("detail_failed", metrics.get("detail_failed", 0)))
    detail_manual_action_required = _to_int(
        event_payload.get(
            "detail_manual_action_required",
            metrics.get("detail_manual_action_required", 0),
        )
    )
    detail_run_completed = _to_int(
        event_payload.get("detail_run_completed", metrics.get("detail_run_completed", 0))
    )
    detail_run_failed = _to_int(
        event_payload.get("detail_run_failed", metrics.get("detail_run_failed", 0))
    )
    detail_run_manual_action_required = _to_int(
        event_payload.get(
            "detail_run_manual_action_required",
            metrics.get("detail_run_manual_action_required", 0),
        )
    )
    status = _derive_progress_status(crawl_job.status, jobs_scraped=jobs_scraped, jobs_saved=jobs_saved)
    phase = _derive_progress_phase(
        crawl_job.status,
        jobs_scraped=jobs_scraped,
        jobs_saved=jobs_saved,
        job_ids_collected=job_ids_collected,
        explicit_phase=event_payload.get("phase"),
        save_total=save_total,
    )
    operator_state = _derive_operator_state(
        status,
        jobs_saved=jobs_saved,
        save_total=save_total,
        detail_pending=detail_pending,
        detail_running=detail_running,
        detail_manual_action_required=detail_manual_action_required,
    )
    metric_scope = _derive_metric_scope(
        status=status,
        operator_state=operator_state,
        phase=phase,
        ai_run_id=event_payload.get("ai_run_id"),
        listings_staged=listings_staged,
        detail_pending=detail_pending,
        detail_running=detail_running,
        detail_completed=detail_completed,
        detail_failed=detail_failed,
        detail_manual_action_required=detail_manual_action_required,
    )

    return {
        "crawl_job_id": str(crawl_job.id),
        "status": status,
        "operator_state": operator_state,
        "metric_scope": metric_scope,
        "phase": phase,
        "category_name": category_label,
        "category_ids": category_ids,
        "source_site": crawl_job.source_site,
        "crawl_mode": resolve_crawl_mode(crawl_job.source_site, request_payload.get("crawl_mode")),
        "trigger_type": crawl_job.trigger_type,
        "schedule_id": str(crawl_job.schedule_id) if crawl_job.schedule_id else None,
        "request_payload": request_payload,
        "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
        "started_at": crawl_job.started_at.isoformat() if crawl_job.started_at else None,
        "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
        "updated_at": crawl_job.updated_at.isoformat() if crawl_job.updated_at else None,
        "elapsed_seconds": _calculate_active_elapsed_seconds(
            crawl_job,
            events=list(events or []),
            now=now,
        ),
        "phase_rate": float(event_payload.get("phase_rate") or 0),
        "eta_seconds": event_payload.get("eta_seconds"),
        "current_job_title": event_payload.get("current_job_title"),
        "detail_job_index": event_payload.get("detail_job_index"),
        "detail_job_total": event_payload.get("detail_job_total"),
        "current_page": event_payload.get("current_page"),
        "total_pages": event_payload.get("total_pages"),
        "job_ids_collected": job_ids_collected,
        "jobs_scraped": jobs_scraped,
        "total_jobs": total_jobs,
        "jobs_saved": jobs_saved,
        "save_total": save_total,
        "jobs_ingested": jobs_saved,
        "detail_selected_rows": detail_selected_rows,
        "detail_skipped_existing_rows": detail_skipped_existing_rows,
        "detail_target_rows": detail_target_rows,
        "detail_run_completed": detail_run_completed,
        "detail_run_failed": detail_run_failed,
        "detail_run_manual_action_required": detail_run_manual_action_required,
        "listings_staged": listings_staged,
        "jobs_skipped_existing": jobs_skipped_existing,
        "detail_pending": detail_pending,
        "detail_running": detail_running,
        "detail_completed": detail_completed,
        "detail_failed": detail_failed,
        "detail_manual_action_required": detail_manual_action_required,
        "jobs_classified": event_payload.get("jobs_classified", metrics.get("jobs_classified", 0)),
        "classification_total": event_payload.get(
            "classification_total",
            metrics.get("classification_total", 0),
        ),
        "ai_run_id": event_payload.get("ai_run_id"),
        "ai_completed_items": event_payload.get("ai_completed_items", metrics.get("ai_completed_items", 0)),
        "ai_failed_items": event_payload.get("ai_failed_items", metrics.get("ai_failed_items", 0)),
        "ai_total_items": event_payload.get("ai_total_items", metrics.get("ai_total_items", 0)),
        "manual_action": event_payload.get("manual_action"),
        "manual_action_resolution": event_payload.get("manual_action_resolution"),
        "error": crawl_job.error_message or event_payload.get("error"),
    }


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _derive_progress_status(status: str, *, jobs_scraped: int, jobs_saved: int) -> str:
    return status


def _derive_operator_state(
    status: str,
    *,
    jobs_saved: int,
    save_total: int,
    detail_pending: int,
    detail_running: int,
    detail_manual_action_required: int,
) -> str:
    if status in ACTIVE_CRAWL_JOB_STATUSES:
        return "live"
    if status in ACTIONABLE_CRAWL_JOB_STATUSES:
        return "manual_action_required"
    has_downstream_backlog = (
        (save_total > 0 and jobs_saved < save_total)
        or detail_pending > 0
        or detail_running > 0
        or detail_manual_action_required > 0
    )
    if status == "completed" and has_downstream_backlog:
        return "completed_with_downstream_backlog"
    if status in TERMINAL_CRAWL_JOB_STATUSES and has_downstream_backlog:
        return "stale_downstream_backlog"
    return status


def _derive_progress_phase(
    status: str,
    *,
    jobs_scraped: int,
    jobs_saved: int,
    job_ids_collected: int,
    explicit_phase: Any,
    save_total: int,
) -> int:
    if status == "queued":
        return 0
    if status == "completed" and save_total > 0 and jobs_saved < save_total:
        return 4
    if explicit_phase is not None:
        return _to_int(explicit_phase)
    if status == "running":
        if jobs_scraped > 0:
            return 2
        return 1
    if status in {"failed", "cancelled"}:
        if save_total > 0 and jobs_saved < save_total:
            return 4
        if jobs_scraped > 0:
            return 2
        if job_ids_collected > 0:
            return 1
    if jobs_scraped > 0:
        return 4
    if job_ids_collected > 0:
        return 1
    return 0


def _derive_metric_scope(
    *,
    status: str,
    operator_state: str,
    phase: int,
    ai_run_id: Any,
    listings_staged: int,
    detail_pending: int,
    detail_running: int,
    detail_completed: int,
    detail_failed: int,
    detail_manual_action_required: int,
) -> str:
    if status == "manual_action_required":
        return "manual_action"

    backlog_counts_visible = any(
        count > 0
        for count in (
            listings_staged,
            detail_pending,
            detail_running,
            detail_completed,
            detail_failed,
            detail_manual_action_required,
        )
    )
    if operator_state in {"completed_with_downstream_backlog", "stale_downstream_backlog"} and backlog_counts_visible:
        return "backlog_pool"

    if phase == 1:
        return "listing_run"
    if phase == 2:
        return "detail_run"
    if phase == 4:
        return "ingest_run"
    if phase == 5 or ai_run_id:
        return "ai_run"

    return "crawl_job"


def _is_snapshot_active(snapshot: dict[str, Any]) -> bool:
    if snapshot["status"] in ACTIVE_CRAWL_JOB_STATUSES:
        return True
    if snapshot["status"] in ACTIONABLE_CRAWL_JOB_STATUSES:
        return True
    return False


def _is_snapshot_backlog(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("operator_state") in {
        "completed_with_downstream_backlog",
        "stale_downstream_backlog",
    }


def _is_snapshot_backlog_visible(snapshot: dict[str, Any], *, crawl_job, now) -> bool:
    if not _is_snapshot_backlog(snapshot):
        return False

    updated_at = getattr(crawl_job, "updated_at", None)
    if updated_at is None:
        return False

    return now - updated_at <= BACKLOG_VISIBLE_WINDOW


def _collect_progress_payload() -> dict[str, Any]:
    now = utc_now()
    all_progress: dict[str, dict[str, Any]] = {}
    active_progress: dict[str, dict[str, Any]] = {}
    backlog_progress: dict[str, dict[str, Any]] = {}

    db = SessionLocal()
    try:
        crawl_jobs_by_id: dict[str, Any] = {}
        for crawl_job in repository.list_crawl_jobs_by_statuses(
            db,
            statuses=ACTIVE_CRAWL_JOB_STATUSES | ACTIONABLE_CRAWL_JOB_STATUSES,
        ):
            crawl_jobs_by_id[str(crawl_job.id)] = crawl_job
        for crawl_job in repository.list_recent_crawl_jobs(db, limit=50):
            crawl_jobs_by_id[str(crawl_job.id)] = crawl_job

        for crawl_job in crawl_jobs_by_id.values():
            latest_event = repository.get_latest_event(db, crawl_job.id)
            events = repository.list_events(
                db,
                crawl_job.id,
                event_types=ACTIVITY_INTERVAL_EVENT_TYPES,
            )
            snapshot = _build_progress_snapshot(crawl_job, latest_event, now=now, events=events)
            key = str(crawl_job.id)
            is_active = _is_snapshot_active(snapshot)
            is_backlog = _is_snapshot_backlog_visible(snapshot, crawl_job=crawl_job, now=now)
            is_recent_terminal = (
                crawl_job.status in TERMINAL_CRAWL_JOB_STATUSES
                and crawl_job.updated_at is not None
                and now - crawl_job.updated_at <= RECENT_TERMINAL_WINDOW
            )
            if is_active or is_recent_terminal or is_backlog:
                all_progress[key] = snapshot
            if is_active:
                active_progress[key] = snapshot
            if is_backlog:
                backlog_progress[key] = snapshot
    finally:
        db.close()

    return {
        "active": active_progress,
        "all": all_progress,
        "backlog": backlog_progress,
        "has_active": len(active_progress) > 0,
        "has_backlog": len(backlog_progress) > 0,
    }


@router.get("/progress/stream")
async def stream_progress():
    """
    SSE endpoint for real-time scraping progress.
    Streams progress updates every second while scraping is active.
    Automatically closes when no active scrapes for 30 seconds.
    """
    async def event_generator():
        idle_count = 0
        max_idle = 30  # Close after 30 seconds of no activity

        while True:
            event_data = _collect_progress_payload()

            # Send SSE event
            yield f"data: {json.dumps(event_data)}\n\n"

            # Track idle time
            if not event_data["has_active"]:
                idle_count += 1
                if idle_count >= max_idle:
                    # Send close event and exit
                    yield f"data: {json.dumps({'closed': True, 'reason': 'idle'})}\n\n"
                    break
            else:
                idle_count = 0

            await asyncio.sleep(1)  # Update every second

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get("/progress")
async def get_progress():
    """
    Get current scraping progress (non-streaming).
    Useful for initial state or polling fallback.
    """
    return _collect_progress_payload()
