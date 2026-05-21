import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.progress import _build_progress_snapshot, _collect_progress_payload
import app.api.progress as progress_module
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


def test_build_progress_snapshot_marks_completed_crawl_with_downstream_backlog_not_running():
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

    assert snapshot["status"] == "completed"
    assert snapshot["operator_state"] == "completed_with_downstream_backlog"
    assert snapshot["phase"] == 4
    assert snapshot["jobs_scraped"] == 3
    assert snapshot["total_jobs"] == 3
    assert snapshot["jobs_saved"] == 1
    assert snapshot["save_total"] == 3
    assert progress_module._is_snapshot_active(snapshot) is False


def test_build_progress_snapshot_exposes_split_pipeline_counters():
    crawl_job = _build_crawl_job(
        status="completed",
        metrics={
            "pages_processed": 3,
            "job_ids_collected": 96,
            "items_emitted": 0,
            "ingest_items_seen": 0,
            "listings_staged": 96,
            "detail_pending": 96,
            "detail_completed": 0,
            "detail_failed": 0,
        },
    )

    snapshot = _build_progress_snapshot(crawl_job, SimpleNamespace(payload={}), now=utc_now())

    assert snapshot["operator_state"] == "completed_with_downstream_backlog"
    assert snapshot["listings_staged"] == 96
    assert snapshot["detail_pending"] == 96
    assert snapshot["detail_completed"] == 0
    assert snapshot["detail_failed"] == 0
    assert snapshot["jobs_ingested"] == 0


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


def test_collect_progress_payload_keeps_older_manual_action_job_visible_outside_recent_limit(monkeypatch):
    now = utc_now()
    older_manual_action_job = _build_crawl_job(
        status="manual_action_required",
        metrics={
            "pages_processed": 51,
            "job_ids_collected": 287,
            "items_emitted": 0,
            "ingest_items_seen": 0,
        },
        started_offset_seconds=7200,
    )
    recent_completed_job = _build_crawl_job(
        status="completed",
        metrics={
            "pages_processed": 2,
            "job_ids_collected": 3,
            "items_emitted": 3,
            "ingest_items_seen": 3,
        },
        started_offset_seconds=15,
    )
    recent_completed_job.updated_at = now

    events_by_job_id = {
        older_manual_action_job.id: [
            SimpleNamespace(
                payload={
                    "manual_action": {
                        "source_site": "ctgoodjobs",
                        "stage": "category_page",
                    }
                }
            )
        ],
        recent_completed_job.id: [SimpleNamespace(payload={})],
    }

    class FakeSession:
        def close(self):
            return None

    class FakeRepository:
        def list_crawl_jobs_by_statuses(self, db, *, statuses):
            assert statuses == (
                progress_module.ACTIVE_CRAWL_JOB_STATUSES | progress_module.ACTIONABLE_CRAWL_JOB_STATUSES
            )
            return [older_manual_action_job]

        def list_recent_crawl_jobs(self, db, *, limit=50):
            assert limit == 50
            return [recent_completed_job]

        def list_events(self, db, crawl_job_id):
            return list(events_by_job_id.get(crawl_job_id, []))

    monkeypatch.setattr(progress_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(progress_module, "repository", FakeRepository())
    monkeypatch.setattr(progress_module, "utc_now", lambda: now)

    payload = _collect_progress_payload()

    assert str(older_manual_action_job.id) in payload["active"]
    assert str(older_manual_action_job.id) in payload["all"]
    assert str(recent_completed_job.id) in payload["all"]


def test_collect_progress_payload_excludes_completed_backlog_from_active(monkeypatch):
    now = utc_now()
    completed_backlog_job = _build_crawl_job(
        status="completed",
        metrics={
            "pages_processed": 2,
            "job_ids_collected": 3,
            "items_emitted": 3,
            "ingest_items_seen": 1,
        },
        started_offset_seconds=15,
    )
    completed_backlog_job.updated_at = now

    class FakeSession:
        def close(self):
            return None

    class FakeRepository:
        def list_crawl_jobs_by_statuses(self, db, *, statuses):
            return []

        def list_recent_crawl_jobs(self, db, *, limit=50):
            return [completed_backlog_job]

        def list_events(self, db, crawl_job_id):
            return []

    monkeypatch.setattr(progress_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(progress_module, "repository", FakeRepository())
    monkeypatch.setattr(progress_module, "utc_now", lambda: now)

    payload = _collect_progress_payload()

    key = str(completed_backlog_job.id)
    assert key not in payload["active"]
    assert payload["all"][key]["operator_state"] == "completed_with_downstream_backlog"
    assert payload["backlog"][key]["operator_state"] == "completed_with_downstream_backlog"
    assert payload["has_active"] is False
