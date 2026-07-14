from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

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
