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
