from __future__ import annotations

from datetime import UTC, timedelta
import redis

from app.config import settings
from app.messaging.topics import STREAM_CRAWL_COMMANDS_HEADED
from app.services.crawl_job_execution_launcher import DIRECT_LAUNCH_SCRIPT_MAP
from app.utils.redis_client import RedisClient
from app.utils.time import utc_now

HEADED_CRAWL_GROUP_NAME = "crawl-headed-workers"
HEADED_CRAWL_DEFAULT_CONSUMER = "crawl-headed-worker"
HEADED_CRAWL_START_COMMAND = r"python backend\scripts\prepare_headed_crawl_worker_host.py"
DIRECT_LAUNCH_HEADED_SOURCES = frozenset({"offertoday", "jobsdb", "ctgoodjobs"})


class HeadedCrawlWorkerUnavailableError(RuntimeError):
    """Raised when a headed crawl is requested without an active headed worker."""


def _isoformat_or_none(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _missing_status(*, reason: str) -> dict[str, object]:
    return {
        "available": False,
        "status": "missing",
        "worker_name": None,
        "consumer_count": 0,
        "pending": 0,
        "lag": None,
        "last_delivered_id": None,
        "heartbeat_status": "missing",
        "heartbeat_age_seconds": None,
        "last_seen_at": None,
        "stale_after_seconds": settings.jobsdb_headed_worker_stale_seconds,
        "reason": reason,
        "start_command": HEADED_CRAWL_START_COMMAND,
    }


def get_headed_crawl_worker_status() -> dict[str, object]:
    try:
        redis_client = RedisClient().redis
        groups = redis_client.xinfo_groups(STREAM_CRAWL_COMMANDS_HEADED)
    except redis.ResponseError as exc:
        if "no such key" in str(exc).lower():
            return _missing_status(reason="headed_worker_missing")
        return {
            **_missing_status(reason="headed_worker_runtime_unavailable"),
            "status": "unknown",
            "heartbeat_status": "unknown",
            "reason": "headed_worker_runtime_unavailable",
        }
    except Exception:
        return {
            **_missing_status(reason="headed_worker_runtime_unavailable"),
            "status": "unknown",
            "heartbeat_status": "unknown",
            "reason": "headed_worker_runtime_unavailable",
        }

    group = next(
        (
            item
            for item in groups
            if str(item.get("name") or "").strip() == HEADED_CRAWL_GROUP_NAME
        ),
        None,
    )
    if group is None:
        return _missing_status(reason="headed_worker_missing")

    try:
        consumers = redis_client.xinfo_consumers(
            STREAM_CRAWL_COMMANDS_HEADED,
            HEADED_CRAWL_GROUP_NAME,
        )
    except redis.ResponseError as exc:
        if "nogroup" in str(exc).lower():
            return _missing_status(reason="headed_worker_missing")
        return {
            **_missing_status(reason="headed_worker_runtime_unavailable"),
            "status": "unknown",
            "heartbeat_status": "unknown",
            "reason": "headed_worker_runtime_unavailable",
        }
    except Exception:
        return {
            **_missing_status(reason="headed_worker_runtime_unavailable"),
            "status": "unknown",
            "heartbeat_status": "unknown",
            "reason": "headed_worker_runtime_unavailable",
        }

    if not consumers:
        return {
            **_missing_status(reason="headed_worker_missing"),
            "pending": int(group.get("pending") or 0),
            "lag": group.get("lag"),
            "last_delivered_id": group.get("last-delivered-id"),
        }

    active_consumer = min(consumers, key=lambda item: int(item.get("idle") or 0))
    idle_ms = max(int(active_consumer.get("idle") or 0), 0)
    heartbeat_age_seconds = idle_ms // 1000
    now = utc_now().astimezone(UTC)
    last_seen_at = now - timedelta(milliseconds=idle_ms)
    is_stale = heartbeat_age_seconds > settings.jobsdb_headed_worker_stale_seconds

    return {
        "available": not is_stale,
        "status": "running" if not is_stale else "stale",
        "worker_name": str(active_consumer.get("name") or HEADED_CRAWL_DEFAULT_CONSUMER),
        "consumer_count": len(consumers),
        "pending": int(group.get("pending") or 0),
        "lag": group.get("lag"),
        "last_delivered_id": group.get("last-delivered-id"),
        "heartbeat_status": "fresh" if not is_stale else "stale",
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "last_seen_at": _isoformat_or_none(last_seen_at),
        "stale_after_seconds": settings.jobsdb_headed_worker_stale_seconds,
        "reason": None if not is_stale else "headed_worker_stale",
        "start_command": HEADED_CRAWL_START_COMMAND,
    }


def ensure_headed_crawl_worker_available(*, crawl_mode: str | None, source_site: str | None = None) -> None:
    if str(crawl_mode or "").strip().lower() != "headed":
        return

    # OfferToday runs headed mode inside the same Docker container — no host-side worker needed
    normalized_source = str(source_site or "").strip().lower()
    if normalized_source in DIRECT_LAUNCH_SCRIPT_MAP or normalized_source in DIRECT_LAUNCH_HEADED_SOURCES:
        return

    status = get_headed_crawl_worker_status()
    if status.get("available") is True:
        return

    raise HeadedCrawlWorkerUnavailableError(
        f"Headed crawl worker is unavailable. Start {HEADED_CRAWL_START_COMMAND} and retry."
    )
