from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.config import settings
from app.database import SessionLocal
from app.messaging.redis_stream_bus import RedisStreamBus
from app.messaging.topics import (
    STREAM_CRAWL_COMMANDS_HEADED,
    STREAM_JOB_INGEST,
    STREAM_JOB_INGEST_DEAD_LETTER,
    STREAM_JOB_LIFECYCLE,
)
from app.models import EnrichmentRun, EventOutbox, Job, JobEmbedding, JobSkillMention
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.utils.time import utc_now

HEADED_WORKER_GROUP = "crawl-headed-workers"

_QUEUE_CONFIGS = (
    {
        "queue_key": STREAM_JOB_INGEST,
        "stream_name": STREAM_JOB_INGEST,
        "group_name": "ingest-workers",
        "worker_name": "ingest-worker",
    },
    {
        "queue_key": f"{STREAM_JOB_LIFECYCLE}:enrichment-workers",
        "stream_name": STREAM_JOB_LIFECYCLE,
        "group_name": "enrichment-workers",
        "worker_name": "enrichment-worker",
    },
    {
        "queue_key": "stream.job.embedding",
        "stream_name": STREAM_JOB_LIFECYCLE,
        "group_name": "embedding-workers",
        "worker_name": "embedding-worker",
    },
    {
        "queue_key": STREAM_CRAWL_COMMANDS_HEADED,
        "stream_name": STREAM_CRAWL_COMMANDS_HEADED,
        "group_name": HEADED_WORKER_GROUP,
        "worker_name": "crawl-headed-worker",
    },
)


def _decode_redis_mapping(row: dict[Any, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = key.decode() if isinstance(key, bytes) else str(key)
        decoded[normalized_key] = value.decode() if isinstance(value, bytes) else value
    return decoded


def _isoformat_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dependency_failure_issue(name: str, exc: Exception) -> str:
    return f"operator dependency {name} unavailable: {exc}"


def _load_dependency(name: str, loader: Callable[[], Any], fallback: Any) -> tuple[Any, str | None]:
    try:
        return loader(), None
    except Exception as exc:  # pragma: no cover - exercised via callers/tests
        return fallback, _dependency_failure_issue(name, exc)


def load_stream_group_summaries(*, bus_factory: Callable[[], Any] = RedisStreamBus) -> dict[str, dict[str, Any]]:
    redis_client = bus_factory().redis
    summaries: dict[str, dict[str, Any]] = {}
    for config in _QUEUE_CONFIGS:
        queue_key = config["queue_key"]
        stream_name = config["stream_name"]
        group_name = config["group_name"]
        summary = {
            "stream": stream_name,
            "group": group_name,
            "worker_name": config["worker_name"],
            "length": 0,
            "pending": 0,
            "lag": 0,
            "consumers": 0,
        }
        summary["length"] = _coerce_int(redis_client.xlen(stream_name))
        group_rows = [_decode_redis_mapping(row) for row in redis_client.xinfo_groups(stream_name)]
        group_row = next((row for row in group_rows if row.get("name") == group_name), None)
        if group_row is None:
            summary["reason"] = "consumer_group_missing"
        else:
            summary["pending"] = _coerce_int(group_row.get("pending"))
            summary["lag"] = _coerce_int(group_row.get("lag"))
            summary["consumers"] = _coerce_int(group_row.get("consumers"))
        summaries[queue_key] = summary
    return summaries


def load_dead_letter_count(*, bus_factory: Callable[[], Any] = RedisStreamBus) -> int:
    return _coerce_int(bus_factory().redis.xlen(STREAM_JOB_INGEST_DEAD_LETTER))


def load_detail_status_counts(
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    repository: CrawlJobListingRepository | None = None,
) -> dict[str, int]:
    db = session_factory()
    try:
        repo = repository or CrawlJobListingRepository()
        return repo.count_detail_statuses(db)
    finally:
        db.close()


def load_outbox_counts(*, session_factory: Callable[[], Any] = SessionLocal) -> dict[str, int]:
    db = session_factory()
    try:
        rows = db.query(EventOutbox.status, func.count(EventOutbox.id)).group_by(EventOutbox.status).all()
        return {str(status): int(count) for status, count in rows}
    finally:
        db.close()


def load_freshness(*, session_factory: Callable[[], Any] = SessionLocal) -> dict[str, Any]:
    db = session_factory()
    try:
        newest_job_updated_at = db.query(func.max(Job.updated_at)).scalar()
        total_jobs = db.query(Job).filter(Job.is_deleted == False).count()
        enriched_jobs = db.query(Job).filter(Job.ai_enriched_at.isnot(None), Job.is_deleted == False).count()
        enrichment_status_rows = db.query(EnrichmentRun.status, func.count(EnrichmentRun.id)).group_by(EnrichmentRun.status).all()
        total_embeddings = db.query(JobEmbedding).count()
        current_embeddings = (
            db.query(JobEmbedding)
            .join(Job, JobEmbedding.job_id == Job.id)
            .filter(Job.is_deleted == False)
            .count()
        )
        newest_skill_mention_at = db.query(func.max(JobSkillMention.created_at)).scalar()
        newest_embedding_at = db.query(func.max(JobEmbedding.updated_at)).scalar()
        pending_jobs = max(int(total_jobs) - int(enriched_jobs), 0)
        missing_current_embeddings = max(int(total_jobs) - int(current_embeddings), 0)

        return {
            "jobs": {
                "total": int(total_jobs),
                "newest_updated_at": _isoformat_or_none(newest_job_updated_at),
            },
            "ai": {
                "total_jobs": int(total_jobs),
                "enriched_jobs": int(enriched_jobs),
                "pending_jobs": pending_jobs,
                "run_status_counts": {str(status): int(count) for status, count in enrichment_status_rows},
            },
            "skills": {
                "newest_mention_at": _isoformat_or_none(newest_skill_mention_at),
            },
            "embeddings": {
                "newest_updated_at": _isoformat_or_none(newest_embedding_at),
                "total_embeddings": int(total_embeddings),
                "current_embeddings": int(current_embeddings),
                "missing_current_embeddings": missing_current_embeddings,
            },
        }
    finally:
        db.close()


def load_scheduler_status() -> dict[str, Any]:
    from app.services.scheduler_runtime import get_scheduler_runtime_status

    return get_scheduler_runtime_status()


def _headed_worker_status_from_summary(worker_summary: dict[str, Any] | None, *, configured: bool) -> tuple[str, str | None]:
    if not configured:
        return "misconfigured", None
    if not worker_summary:
        return "unknown", "headed_worker_status_unavailable"
    if worker_summary.get("reason") == "consumer_group_missing":
        return "unavailable", "headed_worker_group_missing"
    if worker_summary.get("error"):
        return "unavailable", "headed_worker_queue_unavailable"
    if _coerce_int(worker_summary.get("lag")) or _coerce_int(worker_summary.get("pending")):
        return "degraded", "headed_worker_backlog"
    return "healthy", None


def build_headed_runtime_summary(
    runtime_settings: Any = settings,
    *,
    worker_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    browser_channel = str(getattr(runtime_settings, "jobsdb_headed_browser_channel", "") or "").strip() or None
    user_data_dir = str(getattr(runtime_settings, "jobsdb_headed_browser_user_data_dir", "") or "").strip()
    browser_user_data_dir_configured = bool(user_data_dir)
    browser_user_data_dir_exists = bool(user_data_dir) and Path(user_data_dir).is_dir()
    lock_port = _coerce_int(getattr(runtime_settings, "jobsdb_headed_worker_lock_port", 0))

    configured = bool(browser_channel and browser_user_data_dir_configured)
    worker_status, worker_reason = _headed_worker_status_from_summary(worker_summary, configured=configured)

    reason = None
    if not browser_channel:
        reason = "browser_channel_not_configured"
    elif not browser_user_data_dir_configured:
        reason = "browser_user_data_dir_not_configured"
    elif not browser_user_data_dir_exists:
        reason = "browser_user_data_dir_missing"
    elif worker_reason is not None:
        reason = worker_reason

    return {
        "configured": configured,
        "browser_channel": browser_channel,
        "browser_user_data_dir_configured": browser_user_data_dir_configured,
        "browser_user_data_dir_exists": browser_user_data_dir_exists,
        "lock_port": lock_port,
        "worker_group": HEADED_WORKER_GROUP,
        "worker_status": worker_status,
        "reason": reason,
    }


def _normalize_headed_runtime_summary(summary: dict[str, Any]) -> dict[str, Any]:
    raw = dict(summary or {})
    return {
        "configured": bool(raw.get("configured")),
        "browser_channel": str(raw.get("browser_channel") or "").strip() or None,
        "browser_user_data_dir_configured": bool(raw.get("browser_user_data_dir_configured")),
        "browser_user_data_dir_exists": bool(raw.get("browser_user_data_dir_exists")),
        "lock_port": _coerce_int(raw.get("lock_port")),
        "worker_group": str(raw.get("worker_group") or HEADED_WORKER_GROUP),
        "worker_status": str(raw.get("worker_status") or "unknown"),
        "reason": str(raw.get("reason")) if raw.get("reason") is not None else None,
    }


def _headed_runtime_issue(summary: dict[str, Any]) -> str | None:
    reason = summary.get("reason")
    if reason == "browser_channel_not_configured":
        return "headed browser channel is not configured"
    if reason == "browser_user_data_dir_not_configured":
        return "headed browser user data dir is not configured"
    if reason == "browser_user_data_dir_missing":
        return "headed browser user data dir does not exist"
    if reason == "headed_worker_queue_unavailable":
        return "headed worker queue health is unavailable"
    if reason == "headed_worker_backlog":
        return "headed worker queue backlog is present"
    if reason == "headed_worker_status_unavailable":
        return "headed worker status is unavailable"
    if reason == "headed_worker_group_missing":
        return "headed worker consumer group is missing"
    return None


def build_operator_health_summary(
    *,
    queue_summary_loader: Callable[[], dict[str, dict[str, Any]]] = load_stream_group_summaries,
    detail_status_counts_loader: Callable[[], dict[str, int]] = load_detail_status_counts,
    outbox_counts_loader: Callable[[], dict[str, int]] = load_outbox_counts,
    freshness_loader: Callable[[], dict[str, Any]] = load_freshness,
    scheduler_status_loader: Callable[[], dict[str, Any]] = load_scheduler_status,
    headed_runtime_loader: Callable[[], dict[str, Any]] | None = None,
    dead_letter_count_loader: Callable[[], int] = load_dead_letter_count,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    workers: dict[str, dict[str, Any]] = {}
    critical_conditions = False
    degraded_conditions = False

    queue_summaries, queue_error = _load_dependency("queue_summaries", queue_summary_loader, {})
    if queue_error is not None:
        issues.append(queue_error)
        degraded_conditions = True
    queue_summaries = dict(queue_summaries or {})

    queues: dict[str, dict[str, Any]] = {}
    for queue_key, raw_summary in queue_summaries.items():
        raw_summary = dict(raw_summary or {})
        queue_summary = {
            "group": raw_summary.get("group"),
            "length": _coerce_int(raw_summary.get("length")),
            "pending": _coerce_int(raw_summary.get("pending")),
            "lag": _coerce_int(raw_summary.get("lag")),
            "consumers": _coerce_int(raw_summary.get("consumers")),
        }
        if raw_summary.get("stream"):
            queue_summary["stream"] = raw_summary.get("stream")
        worker_name = str(raw_summary.get("worker_name") or queue_key)
        worker_status = "healthy"

        if raw_summary.get("reason") == "consumer_group_missing":
            queue_summary["reason"] = "consumer_group_missing"
            issues.append(f"{queue_key} group {queue_summary['group']} is missing")
            degraded_conditions = True
            worker_status = "unavailable"
        elif raw_summary.get("error"):
            queue_summary["error"] = str(raw_summary["error"])
            issues.append(f"{queue_key} queue health unavailable: {raw_summary['error']}")
            degraded_conditions = True
            worker_status = "unknown"
        else:
            if queue_summary["lag"]:
                issues.append(f"{queue_key} group {queue_summary['group']} lag is {queue_summary['lag']}")
                critical_conditions = True
                worker_status = "degraded"
            if queue_summary["pending"]:
                issues.append(f"{queue_key} group {queue_summary['group']} has {queue_summary['pending']} pending messages")
                critical_conditions = True
                worker_status = "degraded"

        workers[worker_name] = {
            "status": worker_status,
            "stream": queue_summary.get("stream") or queue_key,
            "group": queue_summary["group"],
            "pending": queue_summary["pending"],
            "lag": queue_summary["lag"],
            "consumers": queue_summary["consumers"],
        }
        if raw_summary.get("error"):
            workers[worker_name]["error"] = str(raw_summary["error"])
        if raw_summary.get("reason") == "consumer_group_missing":
            workers[worker_name]["reason"] = "consumer_group_missing"
        queues[queue_key] = queue_summary

    detail_status_counts, detail_error = _load_dependency("detail_status_counts", detail_status_counts_loader, {})
    if detail_error is not None:
        issues.append(detail_error)
        degraded_conditions = True
    detail_status_counts = {str(key): _coerce_int(value) for key, value in dict(detail_status_counts or {}).items()}

    outbox_counts, outbox_error = _load_dependency("outbox_counts", outbox_counts_loader, {})
    if outbox_error is not None:
        issues.append(outbox_error)
        degraded_conditions = True
    outbox_counts = {str(key): _coerce_int(value) for key, value in dict(outbox_counts or {}).items()}

    freshness, freshness_error = _load_dependency("freshness", freshness_loader, {})
    if freshness_error is not None:
        issues.append(freshness_error)
        degraded_conditions = True
    freshness = dict(freshness or {})

    scheduler, scheduler_error = _load_dependency("scheduler_status", scheduler_status_loader, {})
    if scheduler_error is not None:
        issues.append(scheduler_error)
        degraded_conditions = True
    scheduler = dict(scheduler or {})

    if headed_runtime_loader is None:
        headed_runtime = _normalize_headed_runtime_summary(
            build_headed_runtime_summary(
                settings,
                worker_summary=queue_summaries.get(STREAM_CRAWL_COMMANDS_HEADED),
            )
        )
    else:
        headed_runtime_raw, headed_error = _load_dependency("headed_runtime", headed_runtime_loader, {})
        if headed_error is not None:
            issues.append(headed_error)
            degraded_conditions = True
        headed_runtime = _normalize_headed_runtime_summary(headed_runtime_raw)

    dead_letter_count, dead_letter_error = _load_dependency("dead_letter_count", dead_letter_count_loader, 0)
    if dead_letter_error is not None:
        issues.append(dead_letter_error)
        degraded_conditions = True
    dead_letter_count = _coerce_int(dead_letter_count)

    pending_detail_rows = detail_status_counts.get("pending", 0)
    failed_detail_rows = detail_status_counts.get("failed", 0)
    manual_action_detail_rows = detail_status_counts.get("manual_action_required", 0)
    outbox_pending = outbox_counts.get("pending", 0)
    outbox_failed = outbox_counts.get("failed", 0)

    ai_freshness = dict(freshness.get("ai") or {})
    embedding_freshness = dict(freshness.get("embeddings") or {})
    ai_backlog_jobs = _coerce_int((ai_freshness.get("run_status_counts") or {}).get("queued"))
    missing_current_embeddings = _coerce_int(embedding_freshness.get("missing_current_embeddings"))

    freshness["crawl_job_listings"] = detail_status_counts
    freshness["outbox"] = outbox_counts
    freshness["jobs"] = dict(freshness.get("jobs") or {"total": 0, "newest_updated_at": None})
    freshness["ai"] = {
        "total_jobs": _coerce_int(ai_freshness.get("total_jobs")),
        "enriched_jobs": _coerce_int(ai_freshness.get("enriched_jobs")),
        "pending_jobs": _coerce_int(ai_freshness.get("pending_jobs")),
        "run_status_counts": {str(key): _coerce_int(value) for key, value in (ai_freshness.get("run_status_counts") or {}).items()},
    }
    freshness["skills"] = dict(freshness.get("skills") or {"newest_mention_at": None})
    freshness["embeddings"] = {
        "newest_updated_at": embedding_freshness.get("newest_updated_at"),
        "total_embeddings": _coerce_int(embedding_freshness.get("total_embeddings")),
        "current_embeddings": _coerce_int(embedding_freshness.get("current_embeddings")),
        "missing_current_embeddings": missing_current_embeddings,
    }

    if pending_detail_rows:
        issues.append(f"crawl_job_listings has {pending_detail_rows} pending detail rows")
        degraded_conditions = True
    if failed_detail_rows:
        issues.append(f"crawl_job_listings has {failed_detail_rows} failed detail rows")
        degraded_conditions = True
    if manual_action_detail_rows:
        issues.append(f"crawl_job_listings has {manual_action_detail_rows} manual-action detail rows")
        degraded_conditions = True
    if outbox_pending:
        issues.append(f"event_outbox has {outbox_pending} pending rows")
        degraded_conditions = True
    if outbox_failed:
        issues.append(f"event_outbox has {outbox_failed} failed rows")
        degraded_conditions = True
    if dead_letter_count:
        issues.append(f"{STREAM_JOB_INGEST_DEAD_LETTER} has {dead_letter_count} messages")
        degraded_conditions = True
    if missing_current_embeddings:
        total_jobs = _coerce_int(freshness["jobs"].get("total"))
        issues.append(f"embeddings missing for {missing_current_embeddings} of {total_jobs} jobs")
        degraded_conditions = True
    if ai_backlog_jobs:
        issues.append(f"AI run backlog has {ai_backlog_jobs} queued items")
        degraded_conditions = True

    scheduler_worker_name = str(scheduler.get("worker_name") or scheduler.get("owner") or "scheduler-worker")
    heartbeat_status = str(scheduler.get("heartbeat_status") or "unknown")
    workers[scheduler_worker_name] = {
        "status": "healthy" if scheduler.get("available") and heartbeat_status == "fresh" else heartbeat_status,
        "owner": scheduler.get("owner"),
        "last_heartbeat_at": scheduler.get("last_heartbeat_at"),
        "last_reconcile_at": scheduler.get("last_reconcile_at"),
        "active_schedule_count": _coerce_int(scheduler.get("active_schedule_count")),
        "registered_job_count": _coerce_int(scheduler.get("registered_job_count")),
    }
    if heartbeat_status == "missing":
        issues.append("scheduler-worker heartbeat is missing")
        degraded_conditions = True
    elif heartbeat_status == "stale":
        last_seen = scheduler.get("last_heartbeat_at") or "unknown"
        issues.append(f"scheduler-worker heartbeat is stale (last seen {last_seen})")
        degraded_conditions = True
    elif heartbeat_status == "unknown" and scheduler_error is None and scheduler:
        issues.append("scheduler-worker status is unknown")
        degraded_conditions = True
    elif not scheduler.get("available") and scheduler.get("reason"):
        issues.append(f"scheduler-worker status is {scheduler['reason']}")
        degraded_conditions = True

    headed_issue = _headed_runtime_issue(headed_runtime)
    if headed_runtime.get("reason") is not None:
        degraded_conditions = True
        if headed_issue is not None:
            issues.append(headed_issue)

    backlogs = {
        "pending_detail_rows": pending_detail_rows,
        "failed_detail_rows": failed_detail_rows,
        "manual_action_detail_rows": manual_action_detail_rows,
        "outbox_pending": outbox_pending,
        "outbox_failed": outbox_failed,
        "dead_letter_count": dead_letter_count,
        "missing_current_embeddings": missing_current_embeddings,
        "ai_backlog_jobs": ai_backlog_jobs,
    }

    status = "critical" if critical_conditions else "degraded" if degraded_conditions else "healthy"
    return {
        "status": status,
        "generated_at": _isoformat_or_none(generated_at or utc_now()),
        "issues": issues,
        "workers": workers,
        "queues": queues,
        "scheduler": scheduler,
        "headed_runtime": headed_runtime,
        "backlogs": backlogs,
        "freshness": freshness,
    }
