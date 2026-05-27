from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api import ai


def _build_run(*, status: str, failed_items: int):
    return SimpleNamespace(
        id="run-1",
        source_type="manual_pending",
        trigger_crawl_job_id=uuid4(),
        status=status,
        job_ids=[],
        total_items=4,
        pending_items=1,
        completed_items=3,
        failed_items=failed_items,
        started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        completed_at=datetime(2026, 5, 28, 9, 5, tzinfo=UTC),
        created_at=datetime(2026, 5, 28, 8, 59, tzinfo=UTC),
        current_job_title="Title A",
        error_message=None,
    )


def test_serialize_run_skips_failed_title_lookup_when_run_has_no_failed_items(monkeypatch):
    run = _build_run(status="completed", failed_items=0)

    def fail_lookup(db, run_id):
        raise AssertionError("last failed title lookup should be skipped for non-failed runs")

    monkeypatch.setattr(ai, "_derive_last_failed_job_title", fail_lookup)

    payload = ai._serialize_run(run, db=object())

    assert payload["last_failed_job_title"] is None


def test_serialize_run_looks_up_failed_title_when_failed_items_exist(monkeypatch):
    run = _build_run(status="completed_with_failures", failed_items=2)

    def resolve_lookup(db, run_id):
        assert run_id == run.id
        return "Platform Analyst"

    monkeypatch.setattr(ai, "_derive_last_failed_job_title", resolve_lookup)

    payload = ai._serialize_run(run, db=object())

    assert payload["last_failed_job_title"] == "Platform Analyst"
