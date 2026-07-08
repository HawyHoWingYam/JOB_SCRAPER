from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

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
    assert caplog.text.count("PROGRESS_STREAM_CLOSE") == 1
    assert caplog.text.count("PROGRESS_STREAM_STATE") == 2


@pytest.mark.asyncio
async def test_progress_event_generator_logs_close_once_on_early_generator_close(monkeypatch, caplog):
    monkeypatch.setattr(
        progress_api,
        "_collect_progress_payload",
        lambda: {
            "active": {"job-1": {}},
            "all": {"job-1": {}},
            "backlog": {},
            "has_active": True,
            "has_backlog": False,
        },
    )

    generator = progress_api._progress_event_generator(
        request_id="req-2",
        client_stream_id="stream-2",
    )

    with caplog.at_level(logging.INFO, logger="app.api.progress"):
        chunk = await generator.__anext__()
        await generator.aclose()

    assert chunk == 'data: {"active": {"job-1": {}}, "all": {"job-1": {}}, "backlog": {}, "has_active": true, "has_backlog": false}\n\n'
    assert "PROGRESS_STREAM_OPEN request_id=req-2 client_stream_id=stream-2" in caplog.text
    assert "PROGRESS_STREAM_CLOSE request_id=req-2 client_stream_id=stream-2 reason=client_disconnect" in caplog.text
    assert caplog.text.count("PROGRESS_STREAM_CLOSE") == 1
    assert "PROGRESS_STREAM_IDLE" not in caplog.text


@pytest.mark.asyncio
async def test_stream_progress_forwards_request_and_client_stream_ids(monkeypatch):
    captured: dict[str, object] = {}

    def fake_progress_event_generator(*, request_id, client_stream_id, max_idle=30):
        captured["request_id"] = request_id
        captured["client_stream_id"] = client_stream_id
        captured["max_idle"] = max_idle

        async def iterator():
            yield 'data: {"ok": true}\n\n'

        return iterator()

    monkeypatch.setattr(progress_api, "_progress_event_generator", fake_progress_event_generator)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/scrape/progress/stream",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
            "http_version": "1.1",
            "state": {"request_id": "req-3"},
        }
    )

    response = await progress_api.stream_progress(
        request=request,
        client_stream_id="stream-3",
    )

    assert isinstance(response, StreamingResponse)
    assert captured == {
        "request_id": "req-3",
        "client_stream_id": "stream-3",
        "max_idle": 30,
    }


@pytest.mark.asyncio
async def test_progress_event_generator_stays_open_while_backlog_visible(monkeypatch, caplog):
    payloads = iter(
        [
            {"active": {}, "all": {"job-1": {}}, "backlog": {"job-1": {}}, "has_active": False, "has_backlog": True},
            {"active": {}, "all": {"job-1": {}}, "backlog": {"job-1": {}}, "has_active": False, "has_backlog": True},
            {"active": {}, "all": {"job-1": {}}, "backlog": {"job-1": {}}, "has_active": False, "has_backlog": True},
            {"active": {}, "all": {}, "backlog": {}, "has_active": False, "has_backlog": False},
            {"active": {}, "all": {}, "backlog": {}, "has_active": False, "has_backlog": False},
        ]
    )

    monkeypatch.setattr(progress_api, "_collect_progress_payload", lambda: next(payloads))

    async def fast_sleep(_seconds: float):
        return None

    monkeypatch.setattr(progress_api.asyncio, "sleep", fast_sleep)

    generator = progress_api._progress_event_generator(
        request_id="req-backlog",
        client_stream_id="stream-backlog",
        max_idle=2,
    )

    chunks: list[str] = []
    with caplog.at_level(logging.INFO, logger="app.api.progress"):
        for _ in range(7):
            try:
                chunks.append(await generator.__anext__())
            except StopAsyncIteration:
                break

    # While backlog is visible (has_backlog=True, has_active=False) the stream must
    # keep pushing data instead of closing, so completed records remain visible.
    assert len(chunks) >= 4
    assert "closed" not in chunks[0]
    assert "closed" not in chunks[2]
    # Once the backlog clears and `all` is empty, idle counting resumes and closes.
    assert chunks[-1] == 'data: {"closed": true, "reason": "idle"}\n\n'
    assert "PROGRESS_STREAM_IDLE" in caplog.text
    assert "PROGRESS_STREAM_CLOSE" in caplog.text


def test_build_progress_snapshot_includes_listing_and_detail_elapsed_seconds():
    base = datetime(2026, 7, 8, 14, 0, 0, tzinfo=timezone.utc)
    crawl_job = SimpleNamespace(
        id=uuid4(),
        status="completed",
        source_site="offertoday",
        trigger_type="manual",
        schedule_id=None,
        request_payload={"crawl_mode": "headless"},
        queued_at=base,
        started_at=base,
        completed_at=base + timedelta(seconds=400),
        updated_at=base + timedelta(seconds=400),
        error_message=None,
        metrics={},
    )
    started_event = SimpleNamespace(event_type="crawl.started", payload={}, created_at=base)
    listing_done_event = SimpleNamespace(
        event_type="listing_completed",
        payload={"phase": 1},
        created_at=base + timedelta(seconds=120),
    )
    completed_event = SimpleNamespace(
        event_type="crawl.completed",
        payload={},
        created_at=base + timedelta(seconds=400),
    )
    events = [started_event, listing_done_event, completed_event]

    snapshot = _build_progress_snapshot(
        crawl_job,
        completed_event,
        now=base + timedelta(seconds=400),
        events=events,
        category_lookup_cache={},
    )

    assert snapshot["listing_elapsed_seconds"] == 120
    assert snapshot["detail_elapsed_seconds"] == 280
