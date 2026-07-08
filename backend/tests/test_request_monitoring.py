from __future__ import annotations

import importlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from app import request_monitoring
from app.request_monitoring import REQUEST_ID_HEADER, install_request_monitoring

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_test_app():
    app = FastAPI()

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/api/v1/scrape/progress")
    async def progress():
        return {
            "all": {},
            "active": {},
            "backlog": {},
            "has_active": False,
            "has_backlog": False,
        }

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    @app.get("/request-id")
    async def request_id(request: Request):
        return {"request_id": request.state.request_id}

    @app.get("/slow")
    async def slow():
        return {"slow": True}

    @app.get("/api/v1/scrape/progress/stream")
    async def progress_stream():
        async def event_stream():
            yield "data: ok\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return install_request_monitoring(app)


def test_request_monitoring_reuses_incoming_request_id():
    client = TestClient(build_test_app())

    response = client.get("/ok", headers={REQUEST_ID_HEADER: "req-incoming"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req-incoming"


def test_request_monitoring_generates_request_id_when_missing():
    client = TestClient(build_test_app())

    response = client.get("/ok")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers[REQUEST_ID_HEADER].startswith("req-")


def test_request_monitoring_generates_request_id_for_blank_incoming_header():
    client = TestClient(build_test_app())

    response = client.get("/request-id", headers={REQUEST_ID_HEADER: "   "})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER].startswith("req-")
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_request_monitoring_populates_request_state():
    client = TestClient(build_test_app())

    response = client.get("/request-id")

    assert response.status_code == 200
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_request_monitoring_logs_control_plane_and_exception_paths(caplog):
    progress_client = TestClient(build_test_app())
    error_client = TestClient(build_test_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.INFO, logger="app.request_monitoring"):
        progress_response = progress_client.get("/api/v1/scrape/progress")

    assert progress_response.status_code == 200
    assert "API_REQUEST_SUMMARY" in caplog.text
    assert "path=/api/v1/scrape/progress" in caplog.text

    with caplog.at_level(logging.ERROR, logger="app.request_monitoring"):
        error_response = error_client.get("/boom")

    assert error_response.status_code == 500
    assert "API_REQUEST_EXCEPTION" in caplog.text
    assert "path=/boom" in caplog.text


def test_request_monitoring_preserves_default_exception_behavior():
    client = TestClient(build_test_app())

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/boom")


def test_request_monitoring_skips_summary_for_progress_stream(caplog):
    client = TestClient(build_test_app())

    with caplog.at_level(logging.INFO, logger="app.request_monitoring"):
        response = client.get("/api/v1/scrape/progress/stream")

    assert response.status_code == 200
    assert "API_REQUEST_SUMMARY" not in caplog.text
    assert "path=/api/v1/scrape/progress/stream" not in caplog.text


def test_request_monitoring_sets_request_id_on_500_response():
    client = TestClient(build_test_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER]
    assert response.headers[REQUEST_ID_HEADER].startswith("req-")


def test_request_monitoring_quotes_unsafe_incoming_request_id_in_logs(caplog):
    client = TestClient(build_test_app())
    unsafe_request_id = 'req bad status=999'

    with caplog.at_level(logging.INFO, logger="app.request_monitoring"):
        response = client.get(
            "/api/v1/scrape/progress",
            headers={REQUEST_ID_HEADER: unsafe_request_id},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == unsafe_request_id
    assert 'request_id="req bad status=999"' in caplog.text
    assert 'request_id=req bad status=999' not in caplog.text
    assert "status=200" in caplog.text


def test_request_monitoring_logs_5xx_summary_after_exception(caplog):
    client = TestClient(build_test_app(), raise_server_exceptions=False)

    with caplog.at_level(logging.INFO, logger="app.request_monitoring"):
        response = client.get("/boom")

    assert response.status_code == 500
    assert "API_REQUEST_SUMMARY" in caplog.text
    assert "path=/boom" in caplog.text
    assert "status=500" in caplog.text


def test_request_monitoring_logs_slow_request_summary_for_non_control_plane_path(caplog, monkeypatch):
    monkeypatch.setattr(request_monitoring, "SLOW_REQUEST_THRESHOLD_MS", 0)
    client = TestClient(build_test_app())

    with caplog.at_level(logging.INFO, logger="app.request_monitoring"):
        response = client.get("/slow")

    assert response.status_code == 200
    assert "API_REQUEST_SUMMARY" in caplog.text
    assert "path=/slow" in caplog.text


def test_main_module_preserves_fastapi_app_export_and_wrapped_asgi_export():
    dev_compose_text = (PROJECT_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
    main_module = importlib.reload(importlib.import_module("app.main"))
    client = TestClient(main_module.asgi_app)
    response = client.get("/")

    assert "uvicorn app.main:asgi_app" in dev_compose_text
    assert isinstance(main_module.app, FastAPI)
    assert callable(main_module.asgi_app)
    assert main_module.asgi_app is not main_module.app
    assert main_module.app.openapi()["openapi"]
    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER].startswith("req-")
