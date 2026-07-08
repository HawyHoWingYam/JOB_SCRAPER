from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import progress as progress_api
from app.api.progress import _build_progress_snapshot


def test_build_progress_snapshot_accepts_detail_progress_alias_fields():
    now = datetime.now(timezone.utc)
    crawl_job = SimpleNamespace(
        id=uuid4(),
        status="running",
        source_site="offertoday",
        trigger_type="manual",
        schedule_id=None,
        request_payload={"crawl_mode": "headless"},
        queued_at=now,
        started_at=now,
        completed_at=None,
        updated_at=now,
        error_message=None,
        metrics={
            "job_ids_collected": 1286,
            "detail_target_rows": 728,
            "items_emitted": 70,
            "jobs_saved": 70,
        },
    )
    latest_event = SimpleNamespace(
        event_type="crawl.detail_progress",
        payload={
            "detail_ok": 70,
            "detail_fail": 0,
            "detail_total": 728,
            "detail_index": 70,
            "phase": 2,
        },
        created_at=now,
    )

    snapshot = _build_progress_snapshot(
        crawl_job,
        latest_event,
        now=now,
        events=[latest_event],
        category_lookup_cache={},
    )

    assert snapshot["detail_job_index"] == 70
    assert snapshot["detail_job_total"] == 728
    assert snapshot["detail_target_rows"] == 728


@pytest.mark.asyncio
async def test_progress_event_generator_logs_open_idle_and_close_once(monkeypatch, caplog):
    payloads = iter(
        [
            {"active": {"job-1": {}}, "all": {"job-1": {}}, "backlog": {}, "has_active": True, "has_backlog": False},
            {"active": {"job-1": {}}, "all": {"job-1": {}}, "backlog": {}, "has_active": True, "has_backlog": False},
            {"active": {}, "all": {}, "backlog": {}, "has_active": False, "has_backlog": False},
            {"active": {}, "all": {}, "backlog": {}, "has_active": False, "has_backlog": False},
        ]
    )

    monkeypatch.setattr(progress_api, "_collect_progress_payload", lambda: next(payloads))

    async def fast_sleep(_seconds: float):
        return None

    monkeypatch.setattr(progress_api.asyncio, "sleep", fast_sleep)

    generator = progress_api._progress_event_generator(
        request_id="req-1",
        client_stream_id="stream-1",
        max_idle=2,
    )

    with caplog.at_level(logging.INFO, logger="app.api.progress"):
        chunks = [await generator.__anext__() for _ in range(5)]

    assert chunks[-1] == 'data: {"closed": true, "reason": "idle"}\n\n'
    assert "PROGRESS_STREAM_OPEN request_id=req-1 client_stream_id=stream-1" in caplog.text
    assert "PROGRESS_STREAM_IDLE request_id=req-1 client_stream_id=stream-1" in caplog.text
    assert "PROGRESS_STREAM_CLOSE request_id=req-1 client_stream_id=stream-1 reason=idle" in caplog.text
    assert caplog.text.count("PROGRESS_STREAM_STATE") == 2
