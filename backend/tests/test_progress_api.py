import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.progress import _build_progress_snapshot
from app.utils.time import utc_now


def _build_crawl_job(*, status: str, metrics: dict, started_offset_seconds: int = 30, error_message: str | None = None):
    now = utc_now()
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        source_site="jobsdb",
        trigger_type="manual",
        schedule_id=None,
        request_payload={"crawl_mode": "headed", "category_ids": [6281], "max_pages": 2},
        queued_at=now - timedelta(seconds=started_offset_seconds + 5),
        started_at=now - timedelta(seconds=started_offset_seconds),
        completed_at=now if status in {"completed", "failed", "cancelled"} else None,
        updated_at=now,
        error_message=error_message,
        metrics=metrics,
    )


def test_build_progress_snapshot_shows_detail_phase_with_live_save_counters():
    crawl_job = _build_crawl_job(
        status="running",
        metrics={
            "pages_processed": 1,
            "job_ids_collected": 3,
            "items_emitted": 1,
            "ingest_items_seen": 1,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "current_page": 1,
            "total_pages": 2,
            "job_ids_collected": 3,
        }
    )

    snapshot = _build_progress_snapshot(crawl_job, latest_event, now=utc_now())

    assert snapshot["status"] == "running"
    assert snapshot["phase"] == 2
    assert snapshot["jobs_scraped"] == 1
    assert snapshot["total_jobs"] == 3
    assert snapshot["jobs_saved"] == 1
    assert snapshot["save_total"] == 1


def test_build_progress_snapshot_uses_detail_progress_fields_for_live_job_context():
    crawl_job = _build_crawl_job(
        status="running",
        metrics={
            "pages_processed": 1,
            "job_ids_collected": 12,
            "items_emitted": 2,
            "ingest_items_seen": 1,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "phase": 2,
            "current_job_title": "Senior Data Analyst",
            "detail_job_index": 3,
            "detail_job_total": 12,
            "jobs_scraped": 2,
            "total_jobs": 12,
            "phase_rate": 1.5,
            "eta_seconds": 6,
        }
    )

    snapshot = _build_progress_snapshot(crawl_job, latest_event, now=utc_now())

    assert snapshot["phase"] == 2
    assert snapshot["current_job_title"] == "Senior Data Analyst"
    assert snapshot["detail_job_index"] == 3
    assert snapshot["detail_job_total"] == 12
    assert snapshot["phase_rate"] == 1.5
    assert snapshot["eta_seconds"] == 6


def test_build_progress_snapshot_keeps_completed_crawl_active_while_ingest_backlog_remains():
    crawl_job = _build_crawl_job(
        status="completed",
        metrics={
            "pages_processed": 2,
            "job_ids_collected": 3,
            "items_emitted": 3,
            "ingest_items_seen": 1,
        },
    )
    latest_event = SimpleNamespace(
        payload={
            "current_page": 2,
            "total_pages": 2,
            "job_ids_collected": 3,
        }
    )

    snapshot = _build_progress_snapshot(crawl_job, latest_event, now=utc_now())

    assert snapshot["status"] == "running"
    assert snapshot["phase"] == 4
    assert snapshot["jobs_scraped"] == 3
    assert snapshot["total_jobs"] == 3
    assert snapshot["jobs_saved"] == 1
    assert snapshot["save_total"] == 3


def test_build_progress_snapshot_includes_manual_action_details():
    error_message = "CTGoodJobs category_page fetch blocked by human verification"
    crawl_job = _build_crawl_job(
        status="manual_action_required",
        metrics={
            "pages_processed": 51,
            "job_ids_collected": 287,
            "items_emitted": 0,
            "ingest_items_seen": 0,
        },
        error_message=error_message,
    )
    latest_event = SimpleNamespace(
        payload={
            "request_payload": {
                "crawl_mode": "headed",
                "crawl_phase": "listing",
                "category_ids": ["ctgoodjobs:021"],
                "max_pages": 52,
            },
            "manual_action": {
                "source_site": "ctgoodjobs",
                "stage": "category_page",
                "blocked_url": "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52",
            },
            "error": "this value should be ignored when the crawl job already has an error message",
            "pages_processed": 51,
            "job_ids_collected": 287,
        }
    )

    snapshot = _build_progress_snapshot(crawl_job, latest_event, now=utc_now())

    assert {
        "status": snapshot["status"],
        "manual_action": snapshot["manual_action"],
        "error": snapshot["error"],
    } == {
        "status": "manual_action_required",
        "manual_action": {
            "source_site": "ctgoodjobs",
            "stage": "category_page",
            "blocked_url": "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52",
        },
        "error": error_message,
    }
