from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.request_monitoring import REQUEST_ID_HEADER, install_request_monitoring


def build_test_app() -> FastAPI:
    app = FastAPI()
    install_request_monitoring(app)

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

    return app


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
