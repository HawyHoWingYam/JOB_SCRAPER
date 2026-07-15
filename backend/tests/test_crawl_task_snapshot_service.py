from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.crawl_task_snapshot_service import build_crawl_task_snapshot


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _crawl_job(*, metrics=None, request_payload=None, source_site="jobsdb"):
    return SimpleNamespace(
        id="crawl-task",
        status="completed",
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
