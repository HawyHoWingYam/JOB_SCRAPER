from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import TYPE_CHECKING

from app.config import settings
from app.database import SessionLocal
from app.models.schedule import SchedulerRuntimeHeartbeat
from app.utils.time import utc_now

if TYPE_CHECKING:
    from app.services.scheduler_service import SchedulerService

_runtime_service: SchedulerService | None = None
DEFAULT_SCHEDULER_OWNER = "scheduler-worker"


def _scheduler_service_cls():
    from app.services.scheduler_service import SchedulerService

    return SchedulerService


def _default_worker_name() -> str:
    return (os.getenv("WORKER_NAME") or DEFAULT_SCHEDULER_OWNER).strip() or DEFAULT_SCHEDULER_OWNER


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _isoformat_or_none(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized is not None else None


async def initialize_scheduler_runtime(
    *,
    owner: str = DEFAULT_SCHEDULER_OWNER,
    worker_name: str | None = None,
) -> SchedulerService:
    global _runtime_service

    scheduler_service_cls = _scheduler_service_cls()
    if _runtime_service is None:
        _runtime_service = scheduler_service_cls(
            owner=owner,
            worker_name=worker_name or _default_worker_name(),
        )

    await _runtime_service.initialize()
    return _runtime_service


def shutdown_scheduler_runtime() -> None:
    global _runtime_service

    if _runtime_service is not None:
        _runtime_service.shutdown()
        _runtime_service = None


def get_scheduler_runtime_status() -> dict:
    db = SessionLocal()
    try:
        heartbeat = (
            db.query(SchedulerRuntimeHeartbeat)
            .filter(SchedulerRuntimeHeartbeat.id == 1)
            .one_or_none()
        )
    except Exception as exc:
        return {
            "enabled": True,
            "available": False,
            "manual_run_available": True,
            "owner": DEFAULT_SCHEDULER_OWNER,
            "worker_name": None,
            "status": "unknown",
            "running": False,
            "heartbeat_status": "unknown",
            "started_at": None,
            "last_heartbeat_at": None,
            "last_reconcile_at": None,
            "heartbeat_age_seconds": None,
            "stale_after_seconds": settings.scheduler_heartbeat_stale_seconds,
            "active_schedule_count": 0,
            "registered_job_count": 0,
            "last_error": str(exc),
            "reason": "scheduler_runtime_status_unavailable",
        }
    finally:
        db.close()

    if heartbeat is None:
        return {
            "enabled": True,
            "available": False,
            "manual_run_available": True,
            "owner": DEFAULT_SCHEDULER_OWNER,
            "worker_name": None,
            "status": "missing",
            "running": False,
            "heartbeat_status": "missing",
            "started_at": None,
            "last_heartbeat_at": None,
            "last_reconcile_at": None,
            "heartbeat_age_seconds": None,
            "stale_after_seconds": settings.scheduler_heartbeat_stale_seconds,
            "active_schedule_count": 0,
            "registered_job_count": 0,
            "last_error": None,
            "reason": "scheduler_worker_missing",
        }

    last_heartbeat_at = _as_utc(heartbeat.last_heartbeat_at)
    last_reconcile_at = _as_utc(heartbeat.last_reconcile_at)
    started_at = _as_utc(heartbeat.started_at)
    now = utc_now().astimezone(UTC)
    heartbeat_age_seconds = None
    heartbeat_status = "fresh"
    reason = None

    if last_heartbeat_at is not None:
        heartbeat_age_seconds = max(int((now - last_heartbeat_at).total_seconds()), 0)
        if heartbeat_age_seconds > settings.scheduler_heartbeat_stale_seconds:
            heartbeat_status = "stale"
            reason = "scheduler_worker_stale"
    else:
        heartbeat_status = "missing"
        reason = "scheduler_worker_missing"

    running = heartbeat_status == "fresh" and heartbeat.status == "running"
    available = running
    if reason is None and heartbeat.status != "running":
        reason = f"scheduler_worker_{heartbeat.status}"

    return {
        "enabled": True,
        "available": available,
        "manual_run_available": True,
        "owner": heartbeat.owner or DEFAULT_SCHEDULER_OWNER,
        "worker_name": heartbeat.worker_name,
        "status": heartbeat.status,
        "running": running,
        "heartbeat_status": heartbeat_status,
        "started_at": _isoformat_or_none(started_at),
        "last_heartbeat_at": _isoformat_or_none(last_heartbeat_at),
        "last_reconcile_at": _isoformat_or_none(last_reconcile_at),
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_after_seconds": settings.scheduler_heartbeat_stale_seconds,
        "active_schedule_count": int(heartbeat.active_schedule_count or 0),
        "registered_job_count": int(heartbeat.registered_job_count or 0),
        "last_error": heartbeat.last_error,
        "reason": reason,
    }
