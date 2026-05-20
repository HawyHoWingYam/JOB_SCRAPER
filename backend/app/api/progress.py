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
from app.utils.time import utc_now
from app.crawl_modes import resolve_crawl_mode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scrape", tags=["progress"])
repository = CrawlJobRepository()
TERMINAL_CRAWL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_CRAWL_JOB_STATUSES = {"queued", "running", "dispatching"}
ACTIONABLE_CRAWL_JOB_STATUSES = {"manual_action_required"}
RECENT_TERMINAL_WINDOW = timedelta(seconds=60)


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


def _build_progress_snapshot(crawl_job, latest_event, *, now) -> dict[str, Any]:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    request_payload = event_payload.get("request_payload") or crawl_job.request_payload or {}
    category_ids = list(event_payload.get("category_ids") or request_payload.get("category_ids") or [])
    category_label = event_payload.get("category_name")
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
    save_total = _to_int(event_payload.get("save_total", jobs_scraped))
    total_jobs = _to_int(event_payload.get("total_jobs", max(job_ids_collected, jobs_scraped)))
    status = _derive_progress_status(crawl_job.status, jobs_scraped=jobs_scraped, jobs_saved=jobs_saved)
    phase = _derive_progress_phase(
        crawl_job.status,
        jobs_scraped=jobs_scraped,
        jobs_saved=jobs_saved,
        job_ids_collected=job_ids_collected,
        explicit_phase=event_payload.get("phase"),
    )

    return {
        "crawl_job_id": str(crawl_job.id),
        "status": status,
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
        "elapsed_seconds": _elapsed_seconds(now, crawl_job.started_at or crawl_job.queued_at),
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
        "error": crawl_job.error_message or event_payload.get("error"),
    }


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _derive_progress_status(status: str, *, jobs_scraped: int, jobs_saved: int) -> str:
    if status == "completed" and jobs_saved < jobs_scraped:
        return "running"
    return status


def _derive_progress_phase(
    status: str,
    *,
    jobs_scraped: int,
    jobs_saved: int,
    job_ids_collected: int,
    explicit_phase: Any,
) -> int:
    if status == "queued":
        return 0
    if status == "completed" and jobs_saved < jobs_scraped:
        return 4
    if explicit_phase is not None:
        return _to_int(explicit_phase)
    if status == "running":
        if jobs_scraped > 0:
            return 2
        return 1
    if status in {"failed", "cancelled"}:
        if jobs_saved < jobs_scraped:
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


def _is_snapshot_active(snapshot: dict[str, Any]) -> bool:
    if snapshot["status"] in ACTIVE_CRAWL_JOB_STATUSES:
        return True
    if snapshot["status"] in ACTIONABLE_CRAWL_JOB_STATUSES:
        return True
    return _to_int(snapshot.get("jobs_saved")) < _to_int(snapshot.get("save_total"))


def _collect_progress_payload() -> dict[str, Any]:
    now = utc_now()
    all_progress: dict[str, dict[str, Any]] = {}
    active_progress: dict[str, dict[str, Any]] = {}

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
            events = repository.list_events(db, crawl_job.id)
            latest_event = events[-1] if events else None
            snapshot = _build_progress_snapshot(crawl_job, latest_event, now=now)
            key = str(crawl_job.id)
            is_active = _is_snapshot_active(snapshot)
            is_recent_terminal = (
                crawl_job.status in TERMINAL_CRAWL_JOB_STATUSES
                and crawl_job.updated_at is not None
                and now - crawl_job.updated_at <= RECENT_TERMINAL_WINDOW
            )
            if is_active or is_recent_terminal:
                all_progress[key] = snapshot
            if is_active:
                active_progress[key] = snapshot
    finally:
        db.close()

    return {
        "active": active_progress,
        "all": all_progress,
        "has_active": len(active_progress) > 0,
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
