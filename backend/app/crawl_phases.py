from __future__ import annotations

from typing import Iterable, Optional


SUPPORTED_CRAWL_PHASES = {"listing", "detail"}
SUPPORTED_DETAIL_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "manual_action_required",
    "identity_conflict",
}
DEFAULT_DETAIL_RETRY_STATUSES = ("pending", "failed", "manual_action_required")


def normalize_crawl_phase(crawl_phase: Optional[str]) -> Optional[str]:
    if crawl_phase is None:
        return None
    normalized = str(crawl_phase).strip().lower()
    if not normalized:
        return None
    if normalized not in SUPPORTED_CRAWL_PHASES:
        raise ValueError(f"Unsupported crawl_phase: {crawl_phase}")
    return normalized


def resolve_crawl_phase(crawl_phase: Optional[str] = None) -> str:
    return normalize_crawl_phase(crawl_phase) or "listing"


def normalize_detail_statuses(detail_statuses: Iterable[str] | None) -> list[str] | None:
    if detail_statuses is None:
        return None

    normalized: list[str] = []
    for detail_status in detail_statuses:
        value = str(detail_status).strip().lower()
        if not value:
            continue
        if value not in SUPPORTED_DETAIL_STATUSES:
            raise ValueError(f"Unsupported detail_status: {detail_status}")
        normalized.append(value)
    return normalized


def resolve_detail_statuses(
    *,
    crawl_phase: Optional[str],
    detail_statuses: Iterable[str] | None,
) -> list[str]:
    normalized = normalize_detail_statuses(detail_statuses)
    if normalized:
        return normalized

    if resolve_crawl_phase(crawl_phase) == "detail":
        return list(DEFAULT_DETAIL_RETRY_STATUSES)

    return ["pending"]
