from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.api import progress


def _build_crawl_job(*, status: str, request_payload: dict, metrics: dict | None = None):
    now = datetime(2026, 5, 27, 9, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        source_site="jobsdb",
        trigger_type="manual",
        schedule_id=None,
        status=status,
        request_payload=dict(request_payload),
        requested_by="tester",
        queued_at=now,
        started_at=now,
        completed_at=now if status not in {"queued", "running", "dispatching"} else None,
        updated_at=now,
        error_message=None,
        metrics=dict(metrics or {}),
        created_at=now,
    )


def test_build_progress_snapshot_exposes_selected_skipped_and_crawled_detail_scope():
    crawl_job = _build_crawl_job(
        status="completed",
        request_payload={"crawl_phase": "detail", "category_ids": [1200]},
        metrics={
            "detail_selected_rows": 500,
            "detail_skipped_existing_rows": 488,
            "detail_target_rows": 12,
            "items_emitted": 12,
            "ingest_items_seen": 12,
            "detail_run_completed": 12,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "request_payload": {"crawl_phase": "detail", "category_ids": [1200]},
            "phase": 2,
            "category_name": "Engineering",
            "jobs_scraped": 12,
            "total_jobs": 12,
            "jobs_saved": 12,
            "save_total": 12,
        }
    )

    snapshot = progress._build_progress_snapshot(
        crawl_job,
        latest_event,
        now=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        events=[],
    )

    assert snapshot["metric_scope"] == "detail_run"
    assert snapshot["detail_selected_rows"] == 500
    assert snapshot["detail_skipped_existing_rows"] == 488
    assert snapshot["detail_target_rows"] == 12
    assert snapshot["jobs_scraped"] == 12
    assert snapshot["total_jobs"] == 12


def test_build_progress_snapshot_uses_backlog_pool_scope_without_ingest_fallback():
    crawl_job = _build_crawl_job(
        status="completed",
        request_payload={"crawl_phase": "listing", "category_ids": [1200]},
        metrics={
            "listings_staged": 96,
            "detail_pending": 74,
            "detail_completed": 22,
            "detail_manual_action_required": 0,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "request_payload": {"crawl_phase": "listing", "category_ids": [1200]},
            "phase": 1,
            "category_name": "Engineering",
        }
    )

    snapshot = progress._build_progress_snapshot(
        crawl_job,
        latest_event,
        now=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        events=[],
    )

    assert snapshot["operator_state"] == "completed_with_downstream_backlog"
    assert snapshot["metric_scope"] == "backlog_pool"
    assert snapshot["jobs_saved"] == 0
    assert snapshot["save_total"] == 0
    assert snapshot["listings_staged"] == 96
    assert snapshot["detail_pending"] == 74
    assert snapshot["detail_completed"] == 22


def test_build_progress_snapshot_only_exposes_detail_run_manual_review_counts_when_present():
    crawl_job = _build_crawl_job(
        status="running",
        request_payload={"crawl_phase": "detail", "category_ids": [1200]},
        metrics={
            "detail_selected_rows": 5,
            "detail_target_rows": 5,
            "detail_run_manual_action_required": 2,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "request_payload": {"crawl_phase": "detail", "category_ids": [1200]},
            "phase": 2,
            "category_name": "Engineering",
        }
    )

    snapshot = progress._build_progress_snapshot(
        crawl_job,
        latest_event,
        now=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
        events=[],
    )

    assert snapshot["metric_scope"] == "detail_run"
    assert snapshot["detail_run_manual_action_required"] == 2
    assert snapshot["detail_manual_action_required"] == 0


def test_backlog_visibility_keeps_recent_backlog_entries_operator_visible():
    now = datetime(2026, 5, 27, 12, 20, tzinfo=UTC)
    crawl_job = _build_crawl_job(
        status="completed",
        request_payload={"crawl_phase": "listing", "category_ids": [1200]},
        metrics={"detail_pending": 74},
    )
    crawl_job.updated_at = now - timedelta(minutes=10)
    snapshot = {
        "operator_state": "completed_with_downstream_backlog",
    }

    assert progress._is_snapshot_backlog_visible(snapshot, crawl_job=crawl_job, now=now) is True


def test_backlog_visibility_drops_stale_backlog_entries_from_live_progress():
    now = datetime(2026, 5, 27, 12, 20, tzinfo=UTC)
    crawl_job = _build_crawl_job(
        status="completed",
        request_payload={"crawl_phase": "listing", "category_ids": [1200]},
        metrics={"detail_pending": 3193},
    )
    crawl_job.updated_at = now - timedelta(hours=6)
    snapshot = {
        "operator_state": "completed_with_downstream_backlog",
    }

    assert progress._is_snapshot_backlog_visible(snapshot, crawl_job=crawl_job, now=now) is False
