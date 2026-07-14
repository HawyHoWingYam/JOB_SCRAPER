from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import app.services.crawl_task_snapshot_service as snapshot_service
from app.services.crawl_task_snapshot_service import build_crawl_task_snapshot


def _event(event_type: str, payload: dict, created_at: datetime):
    return SimpleNamespace(
        event_type=event_type,
        payload=payload,
        created_at=created_at,
    )


def _crawl_job(
    *,
    source_site: str,
    metrics: dict,
    status: str = "completed",
    request_payload: dict | None = None,
    error_message: str | None = None,
):
    started_at = datetime(2026, 7, 14, 11, 29, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=76)
    return SimpleNamespace(
        id=uuid4(),
        source_site=source_site,
        trigger_type="manual",
        schedule_id=None,
        status=status,
        request_payload=request_payload or {"crawl_phase": "listing", "max_pages": 20},
        queued_at=started_at - timedelta(seconds=2),
        started_at=started_at,
        completed_at=completed_at,
        updated_at=completed_at,
        error_message=error_message,
        metrics=metrics,
    )


def test_offertoday_snapshot_keeps_discovered_and_staged_counts_separate():
    crawl_job = _crawl_job(
        source_site="offertoday",
        metrics={
            "job_ids_collected": 9707,
            "listings_staged": 6969,
            "jobs_skipped_existing": 2738,
            "current_page": 2615,
            "total_pages": 3040,
            "listing_partial": True,
            "listing_condition_count": 152,
            "listing_natural_condition_count": 45,
            "listing_capped_condition_count": 107,
            "detail_target_rows": 0,
        },
    )
    started_event = _event("crawl.started", {}, crawl_job.started_at)
    listing_event = _event(
        "listing_completed",
        {
            "listing_partial": True,
            "listing_condition_count": 152,
            "listing_natural_condition_count": 45,
            "listing_capped_condition_count": 107,
            "job_ids_collected": 9707,
            "listings_staged": 6969,
        },
        crawl_job.completed_at - timedelta(seconds=1),
    )
    completed_event = _event(
        "crawl.completed",
        {"pages": 2615, "listings": 6969},
        crawl_job.completed_at,
    )

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        completed_event,
        now=crawl_job.completed_at,
        events=[started_event, listing_event, completed_event],
    )

    assert snapshot["status"] == "completed"
    assert snapshot["job_ids_collected"] == 9707
    assert snapshot["listings_staged"] == 6969
    assert snapshot["listing_completed"] is True
    assert snapshot["listing_partial"] is True
    assert snapshot["listing_condition_count"] == 152
    assert snapshot["listing_natural_condition_count"] == 45
    assert snapshot["listing_capped_condition_count"] == 107
    assert snapshot["issue_class"] is None
    assert snapshot["waf_challenge"] is False
    assert snapshot["ip_blocked"] is False


def test_non_offertoday_snapshot_preserves_legacy_staged_fallback():
    crawl_job = _crawl_job(
        source_site="jobsdb",
        metrics={"job_ids_collected": 12, "listings_staged": 0},
    )
    completed_event = _event("crawl.completed", {}, crawl_job.completed_at)

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        completed_event,
        now=crawl_job.completed_at,
        events=[completed_event],
    )

    assert snapshot["job_ids_collected"] == 12
    assert snapshot["listings_staged"] == 12
    assert snapshot["listing_partial"] is False


def test_jobs_saved_fallback_is_source_aware():
    offertoday_job = _crawl_job(
        source_site="offertoday",
        metrics={"jobs_saved": 68, "ingest_items_seen": 0},
    )
    jobsdb_job = _crawl_job(
        source_site="jobsdb",
        metrics={"jobs_saved": 3, "ingest_items_seen": 7},
    )

    offertoday_snapshot = build_crawl_task_snapshot(
        offertoday_job,
        _event("crawl.completed", {}, offertoday_job.completed_at),
        now=offertoday_job.completed_at,
    )
    jobsdb_snapshot = build_crawl_task_snapshot(
        jobsdb_job,
        _event("crawl.completed", {}, jobsdb_job.completed_at),
        now=jobsdb_job.completed_at,
    )

    assert offertoday_snapshot["jobs_saved"] == 68
    assert jobsdb_snapshot["jobs_saved"] == 7


def test_legacy_offertoday_ip_block_snapshot_is_resumable_and_actionable():
    request_payload = {
        "crawl_phase": "detail",
        "crawl_mode": "headless",
        "category_ids": [118000],
        "detail_limit": 5000,
    }
    crawl_job = _crawl_job(
        source_site="offertoday",
        metrics={"detail_processed_targets": 191, "detail_target_rows": 1311},
        status="manual_action_required",
        request_payload=request_payload,
        error_message="OfferToday detail phase requires manual action: ip_blocked",
    )
    manual_event = _event(
        "crawl.manual_action_required",
        {
            "request_payload": request_payload,
            "manual_action": {
                "action_type": "session_recovery",
                "classification": "ip_blocked",
                "evidence": {"detail_index": 191, "detail_total": 1311},
                "resume_context": request_payload,
            },
        },
        crawl_job.completed_at,
    )

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        manual_event,
        now=crawl_job.completed_at,
        events=[manual_event],
    )

    assert snapshot["status"] == "manual_action_required"
    assert snapshot["issue_class"] == "ip_blocked"
    assert snapshot["issue_code"] == "-1000035"
    assert snapshot["issue_stage"] == "detail"
    assert snapshot["ip_blocked"] is True
    assert "Change your IP or network" in snapshot["latest_issue_text"]
    assert snapshot["manual_action"]["resume_supported"] is True
    assert snapshot["manual_action"]["reuse_open_browser_supported"] is True
    assert snapshot["manual_action"]["browser_channel"]
    assert snapshot["manual_action"]["browser_profile_path"]


def test_offertoday_snapshot_projects_distinct_resume_safe_detail_progress():
    crawl_job = _crawl_job(
        source_site="offertoday",
        metrics={"detail_target_rows": 1, "detail_run_completed": 9},
        status="manual_action_required",
        request_payload={"crawl_phase": "detail"},
    )
    events = [
        _event(
            "crawl.detail_cohort_frozen",
            {
                "fetch_cohort_source_job_ids": ["a", "b", "c", "d"],
                "fetch_cohort_distinct": 4,
                "reconciled_source_job_ids": ["reconciled-1", "reconciled-2"],
            },
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "a", "classification": "ip_blocked"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "a", "classification": "success"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "a", "classification": "success"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "b", "classification": "terminal_unavailable"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {
                "source_job_id": "c",
                "classification": "transient_transport",
                "will_retry": True,
            },
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "c", "classification": "invalid_payload"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_attempt",
            {"source_job_id": "d", "classification": "waf_challenge"},
            crawl_job.started_at,
        ),
        _event(
            "crawl.detail_cohort_frozen",
            {
                "fetch_cohort_source_job_ids": ["d"],
                "fetch_cohort_distinct": 1,
                "reconciled_source_job_ids": ["reconciled-2", "reconciled-3"],
            },
            crawl_job.completed_at,
        ),
        _event(
            "crawl.detail_reconciled",
            {"records": [{"source_job_id": "reconciled-3"}]},
            crawl_job.completed_at,
        ),
    ]

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        events[-1],
        now=crawl_job.completed_at,
        events=events,
    )

    assert snapshot["detail_distinct_target_total"] == 4
    assert snapshot["detail_distinct_succeeded"] == 1
    assert snapshot["detail_distinct_terminal_unavailable"] == 1
    assert snapshot["detail_distinct_failed"] == 1
    assert snapshot["detail_distinct_reconciled"] == 3
    assert snapshot["detail_distinct_remaining"] == 1


def test_historical_offertoday_detail_snapshot_uses_distinct_event_evidence():
    target_ids = [f"job-{index}" for index in range(1311)]
    reconciled_ids = [f"reconciled-{index}" for index in range(95)]
    crawl_job = _crawl_job(
        source_site="offertoday",
        metrics={
            "detail_target_rows": 68,
            "detail_run_completed": 2464,
            "jobs_saved": 68,
        },
        request_payload={"crawl_phase": "detail"},
    )
    events = [
        _event(
            "crawl.detail_cohort_frozen",
            {
                "fetch_cohort_source_job_ids": target_ids,
                "fetch_cohort_distinct": 1311,
                "reconciled_source_job_ids": reconciled_ids,
            },
            crawl_job.started_at,
        )
    ]
    events.extend(
        _event(
            "crawl.detail_attempt",
            {"source_job_id": target_ids[index], "classification": "ip_blocked"},
            crawl_job.started_at,
        )
        for index in range(5)
    )
    events.extend(
        _event(
            "crawl.detail_attempt",
            {"source_job_id": source_job_id, "classification": "success"},
            crawl_job.completed_at,
        )
        for source_job_id in target_ids[:1305]
    )
    events.extend(
        _event(
            "crawl.detail_attempt",
            {
                "source_job_id": source_job_id,
                "classification": "terminal_unavailable",
            },
            crawl_job.completed_at,
        )
        for source_job_id in target_ids[1305:]
    )
    completed_event = _event("crawl.completed", {}, crawl_job.completed_at)
    events.append(completed_event)

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        completed_event,
        now=crawl_job.completed_at,
        events=events,
    )

    assert snapshot["jobs_saved"] == 68
    assert snapshot["detail_target_rows"] == 68
    assert snapshot["detail_run_completed"] == 2464
    assert snapshot["detail_distinct_target_total"] == 1311
    assert snapshot["detail_distinct_succeeded"] == 1305
    assert snapshot["detail_distinct_terminal_unavailable"] == 6
    assert snapshot["detail_distinct_failed"] == 0
    assert snapshot["detail_distinct_reconciled"] == 95
    assert snapshot["detail_distinct_remaining"] == 0


def test_active_progress_payload_uses_the_same_batched_distinct_projection(monkeypatch):
    crawl_job = _crawl_job(
        source_site="offertoday",
        metrics={"detail_target_rows": 1},
        status="running",
        request_payload={"crawl_phase": "detail"},
    )
    started_event = _event("crawl.started", {}, crawl_job.started_at)
    cohort_event = _event(
        "crawl.detail_cohort_frozen",
        {
            "fetch_cohort_source_job_ids": ["job-1", "job-2"],
            "fetch_cohort_distinct": 2,
            "reconciled_source_job_ids": [],
        },
        crawl_job.started_at,
    )
    attempt_event = _event(
        "crawl.detail_attempt",
        {"source_job_id": "job-1", "classification": "success"},
        crawl_job.started_at,
    )
    observed_event_types = set()

    class _FakeDb:
        def close(self):
            return None

    class _FakeRepository:
        def list_crawl_jobs_by_statuses(self, db, **kwargs):
            return [crawl_job]

        def list_recent_crawl_jobs(self, db, **kwargs):
            return []

        def list_latest_events_for_jobs(self, db, *, crawl_job_ids):
            return {crawl_job.id: attempt_event}

        def list_events_by_job_ids(self, db, *, crawl_job_ids, event_types):
            observed_event_types.update(event_types)
            return {
                crawl_job.id: [started_event, cohort_event, attempt_event],
            }

    monkeypatch.setattr(snapshot_service, "SessionLocal", _FakeDb)

    payload = snapshot_service.collect_progress_payload(
        repository=_FakeRepository()
    )
    snapshot = payload["active"][str(crawl_job.id)]

    assert snapshot["detail_distinct_target_total"] == 2
    assert snapshot["detail_distinct_succeeded"] == 1
    assert snapshot["detail_distinct_remaining"] == 1
    assert {
        "crawl.detail_attempt",
        "crawl.detail_cohort_frozen",
        "crawl.detail_reconciled",
    }.issubset(observed_event_types)
