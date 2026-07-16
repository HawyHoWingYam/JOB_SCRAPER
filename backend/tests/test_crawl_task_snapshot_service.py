from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.crawl_task_snapshot_service import build_crawl_task_snapshot


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _crawl_job(
    *,
    metrics=None,
    request_payload=None,
    source_site="jobsdb",
    status="completed",
):
    return SimpleNamespace(
        id="crawl-task",
        status=status,
        source_site=source_site,
        trigger_type="manual",
        schedule_id=None,
        request_payload=request_payload or {},
        metrics=metrics or {},
        queued_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        updated_at=NOW,
        error_message=None,
    )


def _event(payload, event_type="listing_completed"):
    return SimpleNamespace(
        event_type=event_type,
        payload=dict(payload),
        created_at=NOW,
    )


def test_snapshot_preserves_raw_ids_as_optional_and_uses_larger_counter() -> None:
    event = _event(
        {
            "phase": 1,
            "raw_job_ids_collected": 3,
            "job_ids_collected": 2,
            "listings_staged": 2,
        }
    )
    snapshot = build_crawl_task_snapshot(
        _crawl_job(metrics={"raw_job_ids_collected": 5}),
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["raw_job_ids_collected"] == 5


def test_snapshot_omits_raw_ids_value_for_historical_task_without_field() -> None:
    event = _event({"phase": 1, "job_ids_collected": 2, "listings_staged": 2})

    snapshot = build_crawl_task_snapshot(
        _crawl_job(),
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["raw_job_ids_collected"] is None


def test_snapshot_exposes_normalized_detail_metrics() -> None:
    event = _event(
        {
            "phase": 2,
            "detail_target_rows": 4,
            "detail_completed": 3,
            "detail_reconciled_rows": 1,
            "detail_failed": 2,
            "jobs_saved": 2,
        },
        event_type="crawl.detail_reconciled",
    )

    snapshot = build_crawl_task_snapshot(
        _crawl_job(request_payload={"crawl_phase": "detail"}),
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["detail_target_rows"] == 4
    assert snapshot["detail_reconciled_rows"] == 1
    assert snapshot["detail_fetched"] == 2
    assert snapshot["detail_failed_count"] == 2


def test_snapshot_exposes_common_detail_run_metrics_and_conserves_remaining() -> None:
    event = _event({"phase": 2}, event_type="crawl.detail_progress")
    snapshot = build_crawl_task_snapshot(
        _crawl_job(
            source_site="ctgoodjobs",
            status="running",
            request_payload={"crawl_phase": "detail"},
            metrics={
                "detail_target_rows": 10,
                "detail_run_completed": 3,
                "detail_run_failed": 2,
                "detail_run_terminal_unavailable": 1,
                "detail_run_manual_action_required": 1,
            },
        ),
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["detail_target_count"] == 10
    assert snapshot["detail_fetched_count"] == 3
    assert snapshot["detail_saved_count"] == 3
    assert snapshot["detail_failed_count"] == 2
    assert snapshot["detail_unavailable_count"] == 1
    assert snapshot["detail_manual_action_count"] == 1
    assert snapshot["detail_remaining_count"] == 4


def test_snapshot_common_detail_metrics_are_numeric_zeros() -> None:
    event = _event({"phase": 2}, event_type="crawl.detail_progress")
    snapshot = build_crawl_task_snapshot(
        _crawl_job(
            source_site="jobsdb",
            status="running",
            request_payload={"crawl_phase": "detail"},
        ),
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["detail_target_count"] == 0
    assert snapshot["detail_fetched_count"] == 0
    assert snapshot["detail_saved_count"] == 0
    assert snapshot["detail_failed_count"] == 0
    assert snapshot["detail_unavailable_count"] == 0
    assert snapshot["detail_manual_action_count"] == 0
    assert snapshot["detail_remaining_count"] == 0


def test_snapshot_projects_cancelling_as_live_operator_state() -> None:
    cancel_requested = _event(
        {"status": "cancelling"},
        event_type="crawl.cancel_requested",
    )
    snapshot = build_crawl_task_snapshot(
        _crawl_job(status="cancelling"),
        cancel_requested,
        now=NOW,
        events=[cancel_requested],
    )

    assert snapshot["persisted_status"] == "cancelling"
    assert snapshot["status"] == "cancelling"
    assert snapshot["operator_state"] == "live"


def test_offertoday_common_metrics_prefer_distinct_frozen_cohort() -> None:
    cohort = _event(
        {
            "fetch_cohort_source_job_ids": ["job-1", "job-2", "job-3", "job-4"],
            "fetch_cohort_distinct": 4,
        },
        event_type="crawl.detail_cohort_frozen",
    )
    success = _event(
        {"source_job_id": "job-1", "classification": "success"},
        event_type="crawl.detail_attempt",
    )
    unavailable = _event(
        {"source_job_id": "job-2", "classification": "terminal_unavailable"},
        event_type="crawl.detail_attempt",
    )
    failure = _event(
        {
            "source_job_id": "job-3",
            "classification": "invalid_payload",
            "will_retry": False,
        },
        event_type="crawl.detail_attempt",
    )
    snapshot = build_crawl_task_snapshot(
        _crawl_job(
            source_site="offertoday",
            status="manual_action_required",
            request_payload={"crawl_phase": "detail"},
            metrics={"jobs_saved": 1, "detail_run_manual_action_required": 1},
        ),
        failure,
        now=NOW,
        events=[cohort, success, unavailable, failure],
    )

    assert snapshot["detail_target_count"] == 4
    assert snapshot["detail_fetched_count"] == 1
    assert snapshot["detail_saved_count"] == 1
    assert snapshot["detail_failed_count"] == 1
    assert snapshot["detail_unavailable_count"] == 1
    assert snapshot["detail_manual_action_count"] == 1
    assert snapshot["detail_remaining_count"] == 1


def test_snapshot_projects_detail_segment_and_backlog_metrics() -> None:
    event = _event(
        {
            "phase": 2,
            "detail_scope": "global",
            "segment_index": 2,
            "segment_target_rows": 5000,
            "continuation_state": "continuing",
            "detail_backlog_remaining": 7431,
        },
        event_type="crawl.detail_segment",
    )
    crawl_job = _crawl_job(
        source_site="offertoday",
        request_payload={"crawl_phase": "detail", "detail_scope": "global"},
        metrics={
            "detail_segments_completed": 2,
            "detail_backlog_pending": 7400,
            "detail_backlog_failed": 20,
            "detail_backlog_manual_action_required": 11,
        },
    )

    snapshot = build_crawl_task_snapshot(
        crawl_job,
        event,
        now=NOW,
        events=[event],
    )

    assert snapshot["detail_scope"] == "global"
    assert snapshot["detail_segment_index"] == 2
    assert snapshot["detail_segments_completed"] == 2
    assert snapshot["detail_segment_target_rows"] == 5000
    assert snapshot["detail_backlog_pending"] == 7400
    assert snapshot["detail_backlog_failed"] == 20
    assert snapshot["detail_backlog_manual_action_required"] == 11
    assert snapshot["detail_backlog_remaining"] == 7431
    assert snapshot["detail_continuation_state"] == "continuing"


def test_snapshot_preserves_resumable_manual_action_after_later_progress_event() -> None:
    manual_action_event = _event(
        {
            "request_payload": {
                "crawl_phase": "detail",
                "crawl_mode": "headless",
            },
            "manual_action": {
                "action_type": "session_recovery",
                "source_site": "offertoday",
                "stage": "detail",
                "classification": "ip_blocked",
                "blocked_url": "https://www.offertoday.com/hk/search",
                "resume_supported": True,
                "reuse_open_browser_supported": True,
                "browser_channel": "msedge",
                "browser_profile_path": "C:/profiles/offertoday",
                "preferred_resume_strategy": "reuse_open_browser",
            },
        },
        event_type="crawl.manual_action_required",
    )
    later_progress_event = _event(
        {
            "continuation_state": "manual_action_required",
            "detail_backlog_remaining": 5919,
        },
        event_type="crawl.detail_segment",
    )

    snapshot = build_crawl_task_snapshot(
        _crawl_job(
            source_site="offertoday",
            status="manual_action_required",
            request_payload={"crawl_phase": "detail", "crawl_mode": "headless"},
        ),
        later_progress_event,
        now=NOW,
        events=[manual_action_event, later_progress_event],
    )

    manual_action = snapshot["manual_action"]
    assert manual_action["action_type"] == "session_recovery"
    assert manual_action["source_site"] == "offertoday"
    assert manual_action["stage"] == "detail"
    assert manual_action["classification"] == "ip_blocked"
    assert manual_action["resume_supported"] is True
    assert manual_action["reuse_open_browser_supported"] is True
    assert manual_action["browser_channel"] == "msedge"
    assert manual_action["browser_profile_path"] == "C:/profiles/offertoday"
    assert manual_action["preferred_resume_strategy"] == "reuse_open_browser"
    assert manual_action["resume_context"]["crawl_phase"] == "detail"
    assert manual_action["resume_context"]["crawl_mode"] == "headless"


def test_snapshot_does_not_expose_stale_manual_action_after_completion() -> None:
    manual_action_event = _event(
        {
            "manual_action": {
                "action_type": "session_recovery",
                "classification": "ip_blocked",
                "resume_supported": True,
            }
        },
        event_type="crawl.manual_action_required",
    )
    completed_event = _event({}, event_type="crawl.completed")

    snapshot = build_crawl_task_snapshot(
        _crawl_job(status="completed"),
        completed_event,
        now=NOW,
        events=[manual_action_event, completed_event],
    )

    assert snapshot["manual_action"] is None


def test_snapshot_does_not_inject_jobsdb_browser_defaults_for_offertoday(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.crawl_task_snapshot_service.settings.jobsdb_headed_browser_channel",
        "jobsdb-browser",
    )
    monkeypatch.setattr(
        "app.services.crawl_task_snapshot_service.settings.jobsdb_headed_browser_user_data_dir",
        "C:/profiles/jobsdb",
    )
    manual_action_event = _event(
        {
            "manual_action": {
                "action_type": "session_recovery",
                "source_site": "offertoday",
                "classification": "ip_blocked",
                "resume_supported": True,
            }
        },
        event_type="crawl.manual_action_required",
    )

    snapshot = build_crawl_task_snapshot(
        _crawl_job(source_site="offertoday", status="manual_action_required"),
        manual_action_event,
        now=NOW,
        events=[manual_action_event],
    )

    manual_action = snapshot["manual_action"]
    assert "browser_channel" not in manual_action
    assert "browser_profile_path" not in manual_action
    assert manual_action["reuse_open_browser_supported"] is False


def test_snapshot_projects_recorded_detail_pacing_and_historical_null() -> None:
    pacing = {
        "interval_min_seconds": 1.0,
        "interval_max_seconds": 3.0,
        "burst_size": 20,
        "burst_pause_seconds": 30.0,
    }
    recorded = build_crawl_task_snapshot(
        _crawl_job(request_payload={"crawl_phase": "detail", "detail_pacing": pacing}),
        None,
        now=NOW,
        events=[],
    )
    historical = build_crawl_task_snapshot(
        _crawl_job(request_payload={"crawl_phase": "detail"}),
        None,
        now=NOW,
        events=[],
    )

    assert recorded["detail_pacing"] == pacing
    assert historical["detail_pacing"] is None
    assert "detail_attempt_count" not in recorded

    malformed = build_crawl_task_snapshot(
        _crawl_job(
            request_payload={
                "crawl_phase": "detail",
                "detail_pacing": {"interval_min_seconds": -1},
            }
        ),
        None,
        now=NOW,
        events=[],
    )
    assert malformed["detail_pacing"] is None

    listing = build_crawl_task_snapshot(
        _crawl_job(
            request_payload={"crawl_phase": "listing", "detail_pacing": pacing}
        ),
        None,
        now=NOW,
        events=[],
    )
    assert listing["detail_pacing"] is None
