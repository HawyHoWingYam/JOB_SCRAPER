from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.config import settings
from app.crawl_modes import resolve_crawl_mode
from app.database import SessionLocal
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import normalize_manual_action_payload
from app.services.source_category_registry import get_source_category_registry
from app.utils.time import utc_now

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
TERMINAL_WORK_EVENT_TYPES = {"crawl.completed", "crawl.failed", "crawl.cancelled"}
ACTIVITY_INTERVAL_EVENT_TYPES = ACTIVE_WORK_EVENT_TYPES | INACTIVE_WORK_EVENT_TYPES
DETAIL_PROGRESS_EVENT_TYPES = {
    "crawl.detail_attempt",
    "crawl.detail_cohort_frozen",
    "crawl.detail_reconciled",
}
PROGRESS_CONTEXT_EVENT_TYPES = ACTIVITY_INTERVAL_EVENT_TYPES | {
    "listing_completed",
    "waf.challenge",
    "waf.challenge_cleared",
    "crawl.ip_blocked",
} | DETAIL_PROGRESS_EVENT_TYPES


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


def _phase_elapsed_seconds(
    *,
    start_event: Any | None,
    end_event: Any | None,
    now,
    fallback_running: bool,
) -> int:
    if start_event is None:
        return 0
    start_at = getattr(start_event, "created_at", None)
    if start_at is None:
        return 0
    end_at = getattr(end_event, "created_at", None) if end_event is not None else None
    if end_at is not None:
        return max(0, _elapsed_seconds(end_at, start_at))
    if fallback_running:
        return max(0, _elapsed_seconds(now, start_at))
    return 0


def _latest_event_of_type(events: list[Any] | None, event_type: str) -> Any | None:
    for event in reversed(list(events or [])):
        if getattr(event, "event_type", None) == event_type:
            return event
    return None


def _latest_event_of_types(events: list[Any] | None, event_types: set[str]) -> Any | None:
    for event in reversed(list(events or [])):
        if getattr(event, "event_type", None) in event_types:
            return event
    return None


def _resolve_category_lookup(
    *,
    source_site: str,
    category_lookup_cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, str] | None:
    cache_key = str(source_site)
    if category_lookup_cache is not None and cache_key in category_lookup_cache:
        return category_lookup_cache[cache_key]

    try:
        categories = get_source_category_registry().list_categories(source_site=source_site)
    except Exception:
        return None

    lookup = {
        str(category.get("id")): str(category.get("name"))
        for category in categories
        if isinstance(category, dict) and category.get("id") and category.get("name")
    }
    if category_lookup_cache is not None:
        category_lookup_cache[cache_key] = lookup
    return lookup


def _resolve_category_label(
    *,
    source_site: str,
    category_ids: list[Any],
    category_lookup_cache: dict[str, dict[str, str]] | None = None,
) -> str | None:
    if not category_ids:
        return None

    lookup = _resolve_category_lookup(
        source_site=source_site,
        category_lookup_cache=category_lookup_cache,
    )
    if not lookup:
        return None

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


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _max_count(*values: Any) -> int:
    return max((_to_int(value) for value in values), default=0)


def _normalize_source_job_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_source_job_ids(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {
        normalized
        for item in value
        if (normalized := _normalize_source_job_id(item)) is not None
    }


def _project_distinct_detail_progress(
    events: list[Any] | None,
) -> dict[str, int] | None:
    saw_frozen_cohort = False
    target_total = 0
    target_ids: set[str] | None = None
    succeeded_ids: set[str] = set()
    terminal_ids: set[str] = set()
    failed_ids: set[str] = set()
    reconciled_ids: set[str] = set()
    settled_failure_classifications = {
        "id_mismatch",
        "invalid_payload",
        "persist_failure",
        "transient_transport",
    }

    for event in events or []:
        event_type = getattr(event, "event_type", None)
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue

        if event_type == "crawl.detail_cohort_frozen":
            saw_frozen_cohort = True
            cohort_ids = _normalize_source_job_ids(
                payload.get("fetch_cohort_source_job_ids")
            )
            declared_total = _to_int(payload.get("fetch_cohort_distinct"))
            cohort_total = max(len(cohort_ids), declared_total)
            # Resume cohorts are subsets of the original frozen fetch cohort.
            # Keep the first largest cohort on ties so the original denominator
            # and target universe remain stable across retries.
            if cohort_total > target_total:
                target_total = cohort_total
                target_ids = (
                    cohort_ids
                    if cohort_ids and len(cohort_ids) == cohort_total
                    else None
                )
            reconciled_ids.update(
                _normalize_source_job_ids(payload.get("reconciled_source_job_ids"))
            )
            continue

        if event_type == "crawl.detail_reconciled":
            reconciled_source_job_id = _normalize_source_job_id(
                payload.get("source_job_id")
            )
            if reconciled_source_job_id is not None:
                reconciled_ids.add(reconciled_source_job_id)
            records = payload.get("records")
            if isinstance(records, list):
                reconciled_ids.update(
                    normalized
                    for record in records
                    if isinstance(record, dict)
                    if (
                        normalized := _normalize_source_job_id(
                            record.get("source_job_id")
                        )
                    )
                    is not None
                )
            continue

        if event_type != "crawl.detail_attempt":
            continue

        source_job_id = _normalize_source_job_id(payload.get("source_job_id"))
        classification = str(payload.get("classification") or "").strip().lower()
        if source_job_id is None or not classification:
            continue
        if classification == "success":
            succeeded_ids.add(source_job_id)
        elif classification == "terminal_unavailable":
            terminal_ids.add(source_job_id)
        elif classification in settled_failure_classifications and not bool(
            payload.get("will_retry")
        ):
            failed_ids.add(source_job_id)

    if not saw_frozen_cohort:
        return None

    if target_ids is not None:
        succeeded_ids.intersection_update(target_ids)
        terminal_ids.intersection_update(target_ids)
        failed_ids.intersection_update(target_ids)

    # A successful detail response is the strongest available outcome. Terminal
    # and non-recoverable failure remain mutually exclusive fallbacks. Reconciled
    # IDs are deliberately adjacent to, not part of, the frozen fetch cohort.
    terminal_ids.difference_update(succeeded_ids)
    failed_ids.difference_update(succeeded_ids | terminal_ids)
    settled_total = len(succeeded_ids | terminal_ids | failed_ids)

    return {
        "detail_distinct_target_total": target_total,
        "detail_distinct_succeeded": len(succeeded_ids),
        "detail_distinct_terminal_unavailable": len(terminal_ids),
        "detail_distinct_failed": len(failed_ids),
        "detail_distinct_reconciled": len(reconciled_ids),
        "detail_distinct_remaining": max(target_total - settled_total, 0),
    }


def _event_manual_action(latest_event) -> dict[str, Any]:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    return (
        event_payload.get("manual_action")
        if isinstance(event_payload.get("manual_action"), dict)
        else {}
    )


def _extract_issue_text(
    *,
    latest_event,
    crawl_job,
    manual_action: dict[str, Any] | None = None,
) -> str:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    resolved_manual_action = manual_action or _event_manual_action(latest_event)
    candidates = (
        resolved_manual_action.get("reason"),
        resolved_manual_action.get("message"),
        event_payload.get("error"),
        event_payload.get("message"),
        event_payload.get("detail"),
        getattr(crawl_job, "error_message", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return ""


def _extract_issue_code(
    *,
    latest_event,
    crawl_job,
    manual_action: dict[str, Any] | None = None,
) -> str | None:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    resolved_manual_action = manual_action or _event_manual_action(latest_event)
    candidates = (
        resolved_manual_action.get("code"),
        event_payload.get("code"),
        getattr(crawl_job, "error_code", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        issue_code = str(candidate).strip()
        if issue_code:
            return issue_code
    return None


def _extract_issue_stage(
    latest_event,
    *,
    manual_action: dict[str, Any] | None = None,
) -> str | None:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    resolved_manual_action = manual_action or _event_manual_action(latest_event)
    for candidate in (
        resolved_manual_action.get("stage"),
        event_payload.get("stage"),
    ):
        if candidate is None:
            continue
        issue_stage = str(candidate).strip()
        if issue_stage:
            return issue_stage
    return None


def _derive_issue_metadata(
    latest_event,
    *,
    crawl_job,
    manual_action: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    resolved_manual_action = manual_action or _event_manual_action(latest_event)
    issue_text = _extract_issue_text(
        latest_event=latest_event,
        crawl_job=crawl_job,
        manual_action=resolved_manual_action,
    )
    issue_code = _extract_issue_code(
        latest_event=latest_event,
        crawl_job=crawl_job,
        manual_action=resolved_manual_action,
    )
    issue_stage = _extract_issue_stage(
        latest_event,
        manual_action=resolved_manual_action,
    )
    latest_event_type = str(getattr(latest_event, "event_type", "") or "")
    normalized_issue_text = issue_text.lower()
    classification = str(
        resolved_manual_action.get("classification") or ""
    ).strip().lower()

    if classification == "auth_expired" or issue_code == "1002" or "login expired" in normalized_issue_text:
        issue_class = "session_expired"
    elif (
        classification == "ip_blocked"
        or issue_code == "-1000035"
        or "ip blocked" in normalized_issue_text
        or "ip block" in normalized_issue_text
    ):
        issue_class = "ip_blocked"
    elif issue_code == "2520":
        issue_class = "detail_unavailable"
    elif classification == "waf_challenge" or latest_event_type == "waf.challenge" or "waf" in normalized_issue_text or "verify" in normalized_issue_text or "captcha" in normalized_issue_text:
        issue_class = "waf_challenge"
    elif crawl_job.status == "manual_action_required" or latest_event_type == "crawl.manual_action_required":
        issue_class = "manual_action_required"
    elif issue_text:
        issue_class = "infrastructure_failure"
    else:
        issue_class = None

    return {
        "issue_class": issue_class,
        "issue_code": issue_code,
        "issue_stage": issue_stage,
        "latest_issue_text": issue_text or None,
    }


def _derive_progress_status(
    status: str,
    *,
    jobs_scraped: int,
    jobs_saved: int,
    ai_run_id: Any | None = None,
    ai_completed_items: int = 0,
    ai_failed_items: int = 0,
    ai_total_items: int = 0,
) -> str:
    if (
        status == "completed"
        and ai_run_id
        and ai_total_items > 0
        and (ai_completed_items + ai_failed_items) < ai_total_items
    ):
        return "ai_running"
    if (
        status == "completed"
        and ai_failed_items > 0
        and (ai_run_id or ai_completed_items > 0 or ai_total_items > 0)
    ):
        return "completed_with_ai_failures"
    return status


def _derive_operator_state(
    status: str,
    *,
    jobs_saved: int,
    jobs_settled: int,
    save_total: int,
    detail_pending: int,
    detail_running: int,
    detail_manual_action_required: int,
) -> str:
    if status in ACTIVE_CRAWL_JOB_STATUSES or status == "ai_running":
        return "live"
    if status in ACTIONABLE_CRAWL_JOB_STATUSES:
        return "manual_action_required"
    has_downstream_backlog = (
        (save_total > 0 and jobs_settled < save_total)
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
    jobs_settled: int,
    job_ids_collected: int,
    explicit_phase: Any,
    save_total: int,
) -> int:
    if status == "queued":
        return 0
    if status == "completed" and save_total > 0 and jobs_settled < save_total:
        return 4
    if explicit_phase is not None:
        return _to_int(explicit_phase)
    if status == "running":
        if jobs_scraped > 0:
            return 2
        return 1
    if status in {"failed", "cancelled"}:
        if save_total > 0 and jobs_settled < save_total:
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
    if phase == 5 or ai_run_id:
        return "ai_run"
    if phase == 4:
        return "ingest_run"

    return "crawl_job"


def is_snapshot_active(snapshot: dict[str, Any]) -> bool:
    if snapshot["status"] in ACTIVE_CRAWL_JOB_STATUSES or snapshot["status"] == "ai_running":
        return True
    if snapshot["status"] in ACTIONABLE_CRAWL_JOB_STATUSES:
        return True
    return False


def _is_snapshot_backlog(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("operator_state") in {
        "completed_with_downstream_backlog",
        "stale_downstream_backlog",
    }


def is_snapshot_backlog_visible(snapshot: dict[str, Any], *, crawl_job, now) -> bool:
    if not _is_snapshot_backlog(snapshot):
        return False

    updated_at = getattr(crawl_job, "updated_at", None)
    if updated_at is None:
        return False

    return now - updated_at <= BACKLOG_VISIBLE_WINDOW


def build_crawl_task_snapshot(
    crawl_job,
    latest_event,
    *,
    now,
    events: list[Any] | None = None,
    category_lookup_cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    event_payload = latest_event.payload if latest_event and isinstance(latest_event.payload, dict) else {}
    latest_event_type = getattr(latest_event, "event_type", None)
    listing_completed_event = latest_event if latest_event_type == "listing_completed" else _latest_event_of_type(
        events,
        "listing_completed",
    )
    listing_completed_payload = (
        listing_completed_event.payload
        if listing_completed_event and isinstance(listing_completed_event.payload, dict)
        else {}
    )
    crawl_started_event = _latest_event_of_type(events, "crawl.started")
    terminal_event = _latest_event_of_types(events, TERMINAL_WORK_EVENT_TYPES)
    waf_state_event = latest_event if latest_event_type in {"waf.challenge", "waf.challenge_cleared"} else _latest_event_of_types(
        events,
        {"waf.challenge", "waf.challenge_cleared"},
    )
    listing_completed = listing_completed_event is not None
    waf_challenge = getattr(waf_state_event, "event_type", None) == "waf.challenge"
    waf_event_payload = (
        waf_state_event.payload
        if waf_challenge and waf_state_event and isinstance(waf_state_event.payload, dict)
        else {}
    )
    ip_blocked_state_event = latest_event if latest_event_type == "crawl.ip_blocked" else _latest_event_of_type(
        events,
        "crawl.ip_blocked",
    )
    ip_blocked = ip_blocked_state_event is not None
    ip_blocked_event_payload = (
        ip_blocked_state_event.payload
        if ip_blocked and ip_blocked_state_event and isinstance(ip_blocked_state_event.payload, dict)
        else {}
    )
    request_payload = event_payload.get("request_payload") or crawl_job.request_payload or {}
    manual_action_event = None
    if crawl_job.status == "manual_action_required":
        manual_action_event = (
            latest_event
            if latest_event_type == "crawl.manual_action_required"
            else _latest_event_of_type(events, "crawl.manual_action_required")
        )
    manual_action_event_payload = (
        manual_action_event.payload
        if manual_action_event and isinstance(manual_action_event.payload, dict)
        else {}
    )
    manual_action_request_payload = (
        manual_action_event_payload.get("request_payload") or request_payload
    )
    raw_manual_action = _event_manual_action(manual_action_event)
    source_uses_shared_headed_browser_defaults = str(
        crawl_job.source_site or ""
    ).strip().lower() in {"jobsdb", "ctgoodjobs"}
    manual_action = (
        normalize_manual_action_payload(
            raw_manual_action,
            source_site=crawl_job.source_site,
            request_payload=manual_action_request_payload,
            default_browser_channel=(
                settings.jobsdb_headed_browser_channel
                if source_uses_shared_headed_browser_defaults
                else None
            ),
            default_browser_profile_path=(
                settings.jobsdb_headed_browser_user_data_dir
                if source_uses_shared_headed_browser_defaults
                else None
            ),
        )
        if raw_manual_action
        else None
    )
    category_ids = list(event_payload.get("category_ids") or request_payload.get("category_ids") or [])
    category_label = event_payload.get("category_name")
    if not category_label:
        category_label = _resolve_category_label(
            source_site=crawl_job.source_site,
            category_ids=category_ids,
            category_lookup_cache=category_lookup_cache,
        )
    if not category_label:
        if category_ids:
            category_label = ", ".join(str(category_id) for category_id in category_ids[:3])
            if len(category_ids) > 3:
                category_label = f"{category_label}, +{len(category_ids) - 3}"
        else:
            category_label = f"{crawl_job.source_site} crawl"

    metrics = crawl_job.metrics if isinstance(crawl_job.metrics, dict) else {}
    normalized_source_site = str(crawl_job.source_site or "").strip().lower()
    raw_job_ids_values = (
        event_payload.get("raw_job_ids_collected"),
        metrics.get("raw_job_ids_collected"),
    )
    raw_job_ids_collected = (
        _max_count(*raw_job_ids_values)
        if any(value is not None for value in raw_job_ids_values)
        else None
    )
    job_ids_collected = _max_count(
        event_payload.get("job_ids_collected"),
        metrics.get("job_ids_collected", 0),
        metrics.get("listings_staged", 0),
    )
    search_family = event_payload.get("search_family") or metrics.get("search_family")
    search_families = event_payload.get("search_families") or metrics.get("search_families") or []
    if isinstance(search_families, str):
        search_families = [search_families]
    elif not isinstance(search_families, list):
        search_families = list(search_families)
    jobs_scraped = _to_int(event_payload.get("jobs_scraped", metrics.get("items_emitted", metrics.get("jobs_saved", 0))))
    jobs_saved_fallback = (
        metrics.get("jobs_saved", metrics.get("ingest_items_seen", 0))
        if normalized_source_site == "offertoday"
        else metrics.get("ingest_items_seen", metrics.get("jobs_saved", 0))
    )
    jobs_saved = _to_int(
        event_payload.get(
            "jobs_saved",
            jobs_saved_fallback,
        )
    )
    ingest_items_failed = _to_int(
        event_payload.get("ingest_items_failed", metrics.get("ingest_items_failed", 0))
    )
    ingest_dead_lettered = _to_int(
        event_payload.get("ingest_dead_lettered", metrics.get("ingest_dead_lettered", 0))
    )
    jobs_settled = _to_int(
        event_payload.get(
            "ingest_items_settled",
            metrics.get(
                "ingest_items_settled",
                jobs_saved + max(ingest_items_failed, ingest_dead_lettered),
            ),
        )
    )
    save_total = _to_int(
        event_payload.get(
            "save_total",
            metrics.get("save_total", metrics.get("items_emitted", 0)),
        )
    )
    total_jobs = _to_int(event_payload.get("total_jobs", max(job_ids_collected, jobs_scraped)))
    listings_staged = _max_count(
        event_payload.get("listings_staged"),
        listing_completed_payload.get("listings_staged"),
        metrics.get("listings_staged", 0),
    )
    if normalized_source_site == "offertoday":
        listings_staged = max(listings_staged, _to_int(event_payload.get("listings")))
    else:
        # Preserve the legacy projection for sources whose listing runtimes did
        # not persist a distinct staged-row metric.
        listings_staged = max(listings_staged, job_ids_collected)
    listing_partial = any(
        bool(payload.get("listing_partial"))
        for payload in (event_payload, listing_completed_payload, metrics)
    )
    listing_condition_count = _max_count(
        event_payload.get("listing_condition_count"),
        listing_completed_payload.get("listing_condition_count"),
        metrics.get("listing_condition_count", 0),
    )
    listing_natural_condition_count = _max_count(
        event_payload.get("listing_natural_condition_count"),
        listing_completed_payload.get("listing_natural_condition_count"),
        metrics.get("listing_natural_condition_count", 0),
    )
    listing_capped_condition_count = _max_count(
        event_payload.get("listing_capped_condition_count"),
        listing_completed_payload.get("listing_capped_condition_count"),
        metrics.get("listing_capped_condition_count", 0),
    )
    jobs_skipped_existing = _max_count(
        event_payload.get("jobs_skipped_existing"),
        metrics.get("jobs_skipped_existing", 0),
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
    detail_scope = (
        event_payload.get("detail_scope")
        or metrics.get("detail_scope")
        or request_payload.get("detail_scope")
    )
    detail_segment_index = _to_int(
        event_payload.get(
            "detail_segment_index",
            event_payload.get("segment_index", metrics.get("detail_segment_index", 0)),
        )
    )
    detail_segments_completed = _to_int(
        event_payload.get(
            "detail_segments_completed",
            metrics.get("detail_segments_completed", 0),
        )
    )
    detail_segment_target_rows = _to_int(
        event_payload.get(
            "detail_segment_target_rows",
            event_payload.get(
                "segment_target_rows",
                metrics.get("detail_segment_target_rows", 0),
            ),
        )
    )
    detail_backlog_pending = _to_int(
        event_payload.get(
            "detail_backlog_pending",
            metrics.get("detail_backlog_pending", 0),
        )
    )
    detail_backlog_failed = _to_int(
        event_payload.get(
            "detail_backlog_failed",
            metrics.get("detail_backlog_failed", 0),
        )
    )
    detail_backlog_manual_action_required = _to_int(
        event_payload.get(
            "detail_backlog_manual_action_required",
            metrics.get("detail_backlog_manual_action_required", 0),
        )
    )
    detail_backlog_remaining = _to_int(
        event_payload.get(
            "detail_backlog_remaining",
            metrics.get("detail_backlog_remaining", 0),
        )
    )
    detail_continuation_state = (
        event_payload.get("detail_continuation_state")
        or event_payload.get("continuation_state")
        or metrics.get("detail_continuation_state")
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
    detail_reconciled_rows = _to_int(
        event_payload.get(
            "detail_reconciled_rows",
            metrics.get("detail_reconciled_rows", 0),
        )
    )
    detail_distinct_progress = (
        _project_distinct_detail_progress(events)
        if normalized_source_site == "offertoday"
        else None
    )
    if detail_distinct_progress is not None:
        detail_fetched = _to_int(detail_distinct_progress["detail_distinct_succeeded"])
        detail_failed_count = _to_int(detail_distinct_progress["detail_distinct_failed"])
    else:
        detail_fetched = max(detail_completed - detail_reconciled_rows, 0)
        detail_failed_count = _max_count(
            detail_failed,
            detail_run_failed,
            ingest_items_failed,
        )
    ai_run_id = event_payload.get("ai_run_id") or metrics.get("ai_run_id")
    ai_completed_items = _to_int(
        event_payload.get("ai_completed_items", metrics.get("ai_completed_items", 0))
    )
    ai_failed_items = _to_int(
        event_payload.get("ai_failed_items", metrics.get("ai_failed_items", 0))
    )
    ai_total_items = _to_int(
        event_payload.get("ai_total_items", metrics.get("ai_total_items", 0))
    )
    status = _derive_progress_status(
        crawl_job.status,
        jobs_scraped=jobs_scraped,
        jobs_saved=jobs_saved,
        ai_run_id=ai_run_id,
        ai_completed_items=ai_completed_items,
        ai_failed_items=ai_failed_items,
        ai_total_items=ai_total_items,
    )
    phase = _derive_progress_phase(
        crawl_job.status,
        jobs_scraped=jobs_scraped,
        jobs_saved=jobs_saved,
        jobs_settled=jobs_settled,
        job_ids_collected=job_ids_collected,
        explicit_phase=event_payload.get("phase"),
        save_total=save_total,
    )
    operator_state = _derive_operator_state(
        status,
        jobs_saved=jobs_saved,
        jobs_settled=jobs_settled,
        save_total=save_total,
        detail_pending=detail_pending,
        detail_running=detail_running,
        detail_manual_action_required=detail_manual_action_required,
    )
    metric_scope = _derive_metric_scope(
        status=status,
        operator_state=operator_state,
        phase=phase,
        ai_run_id=ai_run_id,
        listings_staged=listings_staged,
        detail_pending=detail_pending,
        detail_running=detail_running,
        detail_completed=detail_completed,
        detail_failed=detail_failed,
        detail_manual_action_required=detail_manual_action_required,
    )

    detail_job_index = event_payload.get("detail_job_index")
    if detail_job_index is None:
        detail_job_index = event_payload.get("detail_index")

    detail_job_total = event_payload.get("detail_job_total")
    if detail_job_total is None:
        detail_job_total = event_payload.get("detail_total")
    if detail_job_total is None:
        detail_job_total = detail_target_rows or None

    is_running = crawl_job.status == "running"
    listing_elapsed_seconds = _phase_elapsed_seconds(
        start_event=crawl_started_event,
        end_event=listing_completed_event,
        now=now,
        fallback_running=is_running,
    )
    detail_elapsed_seconds = _phase_elapsed_seconds(
        start_event=listing_completed_event,
        end_event=terminal_event,
        now=now,
        fallback_running=is_running,
    )
    issue_metadata = _derive_issue_metadata(
        latest_event,
        crawl_job=crawl_job,
        manual_action=manual_action,
    )
    ip_blocked = ip_blocked or issue_metadata["issue_class"] == "ip_blocked"

    return {
        "crawl_job_id": str(crawl_job.id),
        "persisted_status": crawl_job.status,
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
        "listing_elapsed_seconds": listing_elapsed_seconds,
        "detail_elapsed_seconds": detail_elapsed_seconds,
        "search_family": search_family,
        "search_families": search_families,
        "phase_rate": float(event_payload.get("phase_rate") or 0),
        "eta_seconds": event_payload.get("eta_seconds"),
        "current_job_title": event_payload.get("current_job_title"),
        "detail_job_index": detail_job_index,
        "detail_job_total": detail_job_total,
        "current_page": event_payload.get("current_page") or metrics.get("current_page"),
        "total_pages": event_payload.get("total_pages") or metrics.get("total_pages"),
        "job_ids_collected": job_ids_collected,
        "raw_job_ids_collected": raw_job_ids_collected,
        "jobs_scraped": jobs_scraped,
        "total_jobs": total_jobs,
        "jobs_saved": jobs_saved,
        "save_total": save_total,
        "jobs_ingested": jobs_saved,
        "ingest_items_settled": jobs_settled,
        "ingest_items_failed": ingest_items_failed,
        "ingest_dead_lettered": ingest_dead_lettered,
        "detail_selected_rows": detail_selected_rows,
        "detail_skipped_existing_rows": detail_skipped_existing_rows,
        "detail_target_rows": detail_target_rows,
        "detail_scope": detail_scope,
        "detail_segment_index": detail_segment_index,
        "detail_segments_completed": detail_segments_completed,
        "detail_segment_target_rows": detail_segment_target_rows,
        "detail_backlog_pending": detail_backlog_pending,
        "detail_backlog_failed": detail_backlog_failed,
        "detail_backlog_manual_action_required": detail_backlog_manual_action_required,
        "detail_backlog_remaining": detail_backlog_remaining,
        "detail_continuation_state": detail_continuation_state,
        "detail_run_completed": detail_run_completed,
        "detail_run_failed": detail_run_failed,
        "detail_run_manual_action_required": detail_run_manual_action_required,
        "detail_reconciled_rows": detail_reconciled_rows,
        "detail_fetched": detail_fetched,
        "detail_failed_count": detail_failed_count,
        **(
            detail_distinct_progress
            or {
                "detail_distinct_target_total": None,
                "detail_distinct_succeeded": None,
                "detail_distinct_terminal_unavailable": None,
                "detail_distinct_failed": None,
                "detail_distinct_reconciled": None,
                "detail_distinct_remaining": None,
            }
        ),
        "listings_staged": listings_staged,
        "jobs_skipped_existing": jobs_skipped_existing,
        "detail_pending": detail_pending,
        "detail_running": detail_running,
        "detail_completed": detail_completed,
        "detail_failed": detail_failed,
        "detail_manual_action_required": detail_manual_action_required,
        "jobs_classified": event_payload.get("jobs_classified", metrics.get("jobs_classified", 0)),
        "new_jobs_added": event_payload.get("new_jobs_added") or metrics.get("new_jobs_added") or metrics.get("new_jobs_count", 0),
        "classification_total": event_payload.get(
            "classification_total",
            metrics.get("classification_total", 0),
        ),
        "ai_run_id": ai_run_id,
        "ai_completed_items": ai_completed_items,
        "ai_failed_items": ai_failed_items,
        "ai_total_items": ai_total_items,
        "manual_action": manual_action,
        "manual_action_resolution": event_payload.get("manual_action_resolution"),
        **issue_metadata,
        "listing_completed": listing_completed,
        "listing_partial": listing_partial,
        "listing_condition_count": listing_condition_count,
        "listing_natural_condition_count": listing_natural_condition_count,
        "listing_capped_condition_count": listing_capped_condition_count,
        "waf_challenge": waf_challenge,
        "waf_challenge_message": waf_event_payload.get("message") if waf_challenge else None,
        "waf_challenge_url": waf_event_payload.get("challenge_url") if waf_challenge else None,
        "ip_blocked": ip_blocked,
        "ip_blocked_message": (
            ip_blocked_event_payload.get("message")
            or issue_metadata["latest_issue_text"]
            if ip_blocked
            else None
        ),
        "error": crawl_job.error_message or event_payload.get("error"),
    }


def collect_progress_payload(*, repository: CrawlJobRepository | None = None) -> dict[str, Any]:
    repo = repository or CrawlJobRepository()
    now = utc_now()
    all_progress: dict[str, dict[str, Any]] = {}
    active_progress: dict[str, dict[str, Any]] = {}
    backlog_progress: dict[str, dict[str, Any]] = {}
    category_lookup_cache: dict[str, dict[str, str]] = {}

    db = SessionLocal()
    try:
        crawl_jobs_by_id: dict[str, Any] = {}
        for crawl_job in repo.list_crawl_jobs_by_statuses(
            db,
            statuses=ACTIVE_CRAWL_JOB_STATUSES | ACTIONABLE_CRAWL_JOB_STATUSES,
            limit=50,
        ):
            crawl_jobs_by_id[str(crawl_job.id)] = crawl_job
        for crawl_job in repo.list_recent_crawl_jobs(
            db,
            limit=50,
            updated_since=now - BACKLOG_VISIBLE_WINDOW,
            statuses=TERMINAL_CRAWL_JOB_STATUSES,
        ):
            crawl_jobs_by_id[str(crawl_job.id)] = crawl_job

        crawl_jobs = list(crawl_jobs_by_id.values())
        crawl_job_ids = [crawl_job.id for crawl_job in crawl_jobs]
        latest_events_by_job = repo.list_latest_events_for_jobs(
            db,
            crawl_job_ids=crawl_job_ids,
        )
        activity_events_by_job = repo.list_events_by_job_ids(
            db,
            crawl_job_ids=crawl_job_ids,
            event_types=PROGRESS_CONTEXT_EVENT_TYPES,
        )

        for crawl_job in crawl_jobs:
            latest_event = latest_events_by_job.get(crawl_job.id)
            events = activity_events_by_job.get(crawl_job.id, [])
            snapshot = build_crawl_task_snapshot(
                crawl_job,
                latest_event,
                now=now,
                events=events,
                category_lookup_cache=category_lookup_cache,
            )
            key = str(crawl_job.id)
            snapshot_is_active = is_snapshot_active(snapshot)
            snapshot_is_backlog = is_snapshot_backlog_visible(snapshot, crawl_job=crawl_job, now=now)
            is_recent_terminal = (
                crawl_job.status in TERMINAL_CRAWL_JOB_STATUSES
                and crawl_job.updated_at is not None
                and now - crawl_job.updated_at <= RECENT_TERMINAL_WINDOW
            )
            if snapshot_is_active or is_recent_terminal or snapshot_is_backlog:
                all_progress[key] = snapshot
            if snapshot_is_active:
                active_progress[key] = snapshot
            if snapshot_is_backlog:
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
