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


def test_collect_progress_payload_uses_batched_latest_and_filtered_activity_events(monkeypatch):
    now = datetime(2026, 5, 27, 12, 20, tzinfo=UTC)
    crawl_job = _build_crawl_job(
        status="running",
        request_payload={"crawl_phase": "detail", "category_ids": [1200]},
        metrics={"items_emitted": 2},
    )
    crawl_job.updated_at = now
    expected_event_types = progress.ACTIVE_WORK_EVENT_TYPES | progress.INACTIVE_WORK_EVENT_TYPES
    latest_event = SimpleNamespace(
        payload={
            "request_payload": {"crawl_phase": "detail", "category_ids": [1200]},
            "phase": 2,
            "category_name": "Engineering",
            "jobs_scraped": 2,
            "total_jobs": 2,
        }
    )
    activity_events = [
        SimpleNamespace(
            event_type="crawl.started",
            created_at=now - timedelta(minutes=5),
        )
    ]

    class _RepositoryStub:
        def __init__(self):
            self.latest_event_batch_calls: list[list] = []
            self.activity_event_batch_calls: list[tuple[list, set[str] | None]] = []

        def list_crawl_jobs_by_statuses(self, db, *, statuses):
            return [crawl_job]

        def list_recent_crawl_jobs(self, db, *, limit):
            return []

        def list_latest_events_for_jobs(self, db, *, crawl_job_ids):
            self.latest_event_batch_calls.append(list(crawl_job_ids))
            assert list(crawl_job_ids) == [crawl_job.id]
            return {crawl_job.id: latest_event}

        def list_events_by_job_ids(self, db, *, crawl_job_ids, event_types=None):
            self.activity_event_batch_calls.append(
                (list(crawl_job_ids), set(event_types) if event_types is not None else None)
            )
            assert list(crawl_job_ids) == [crawl_job.id]
            assert set(event_types or set()) == expected_event_types
            return {crawl_job.id: activity_events}

        def get_latest_event(self, db, crawl_job_id):
            raise AssertionError("progress payload should batch latest event lookups")

        def list_events(self, db, crawl_job_id, event_types=None):
            raise AssertionError("progress payload should batch activity event lookups")

    class _SessionStub:
        def close(self):
            return None

    repository_stub = _RepositoryStub()

    monkeypatch.setattr(progress, "repository", repository_stub)
    monkeypatch.setattr(progress, "SessionLocal", lambda: _SessionStub())
    monkeypatch.setattr(progress, "utc_now", lambda: now)

    payload = progress._collect_progress_payload()

    assert repository_stub.latest_event_batch_calls == [[crawl_job.id]]
    assert repository_stub.activity_event_batch_calls == [([crawl_job.id], expected_event_types)]
    assert payload["has_active"] is True
    assert payload["active"][str(crawl_job.id)]["jobs_scraped"] == 2


def test_collect_progress_payload_reuses_category_registry_lookup_per_source(monkeypatch):
    now = datetime(2026, 5, 27, 12, 20, tzinfo=UTC)
    first_job = _build_crawl_job(
        status="running",
        request_payload={"crawl_phase": "listing", "category_ids": [1200]},
    )
    second_job = _build_crawl_job(
        status="running",
        request_payload={"crawl_phase": "listing", "category_ids": [1300]},
    )
    second_job.source_site = first_job.source_site
    second_job.updated_at = now

    class _RepositoryStub:
        def list_crawl_jobs_by_statuses(self, db, *, statuses):
            return [first_job, second_job]

        def list_recent_crawl_jobs(self, db, *, limit):
            return []

        def list_latest_events_for_jobs(self, db, *, crawl_job_ids):
            assert list(crawl_job_ids) == [first_job.id, second_job.id]
            return {
                first_job.id: SimpleNamespace(payload={"request_payload": first_job.request_payload}),
                second_job.id: SimpleNamespace(payload={"request_payload": second_job.request_payload}),
            }

        def list_events_by_job_ids(self, db, *, crawl_job_ids, event_types=None):
            assert list(crawl_job_ids) == [first_job.id, second_job.id]
            return {}

        def get_latest_event(self, db, crawl_job_id):
            raise AssertionError("progress payload should batch latest event lookups")

        def list_events(self, db, crawl_job_id, event_types=None):
            raise AssertionError("progress payload should batch activity event lookups")

    class _RegistryStub:
        def __init__(self):
            self.calls = 0

        def list_categories(self, *, source_site=None):
            self.calls += 1
            assert source_site == "jobsdb"
            return [
                {"id": 1200, "name": "Engineering"},
                {"id": 1300, "name": "Marketing"},
            ]

    class _SessionStub:
        def close(self):
            return None

    repository_stub = _RepositoryStub()
    registry_stub = _RegistryStub()

    monkeypatch.setattr(progress, "repository", repository_stub)
    monkeypatch.setattr(progress, "SessionLocal", lambda: _SessionStub())
    monkeypatch.setattr(progress, "utc_now", lambda: now)
    monkeypatch.setattr(progress, "get_source_category_registry", lambda: registry_stub)

    payload = progress._collect_progress_payload()

    assert registry_stub.calls == 1
    assert payload["active"][str(first_job.id)]["category_name"] == "Engineering"
    assert payload["active"][str(second_job.id)]["category_name"] == "Marketing"
