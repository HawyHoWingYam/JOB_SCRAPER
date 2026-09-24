from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import jev as jev_api
from app.api.jev import router
from app.database import get_db
from app.models.jev import (
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


def _client(*, endpoint: str = "https://openrouter.ai/api/alpha/decisions"):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        settings = JevRuntimeSettingsService(db)
        settings.get_or_create()
        settings.update(
            {
                "enabled": True,
                "endpoint": endpoint,
                "api_key": "test-secret",
            }
        )
        db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return engine, TestClient(app)


def test_jev_run_http_lifecycle_freezes_reads_and_stops_without_dispatch() -> None:
    engine, client = _client()
    try:
        created = client.post(
            "/api/jev/runs",
            json={
                "purpose": "skill_evidence_evaluation",
                "rubric_version": "skill-evidence-v1",
                "items": [
                    {
                        "subject_id": "job-2:python",
                        "payload": {
                            "state": {"text": "Python required"},
                            "questions": {
                                "support": {
                                    "type": "noul",
                                    "instructions": "Is Python required?",
                                }
                            },
                        },
                    }
                ],
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "pending"
        assert body["total_items"] == 1
        assert body["settings_snapshot"]["model"] == "~typesafe/jev-latest"
        assert "api_key" not in body["settings_snapshot"]
        assert body["items"][0]["status"] == "pending"

        fetched = client.get(f"/api/jev/runs/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == body

        stopped = client.post(f"/api/jev/runs/{body['id']}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "cancelled"
        assert stopped.json()["cancelled_items"] == 1

        listed = client.get("/api/jev/runs")
        assert listed.status_code == 200
        assert [run["id"] for run in listed.json()["runs"]] == [body["id"]]

        resumed = client.post(f"/api/jev/runs/{body['id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "pending"
        assert resumed.json()["pending_items"] == 1
    finally:
        engine.dispose()


def test_jev_http_end_to_end_uses_provider_console_limits_and_receipt() -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib HTTP handler contract
            length = int(self.headers.get("content-length", "0"))
            received.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "body": json.loads(self.rfile.read(length)),
                }
            )
            body = json.dumps(
                {
                    "model": "jev-latest",
                    "answers": {"support": {"type": "noul", "noul": 0.97}},
                    "usage": {"input_tokens": 11, "output_tokens": 1},
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/systemone"
    engine, client = _client(endpoint=endpoint)
    try:
        created = client.post(
            "/api/jev/runs",
            json={
                "purpose": "skill_evidence_evaluation",
                "rubric_version": "skill-evidence-v1",
                "items": [
                    {
                        "subject_id": "job-2:python",
                        "payload": {
                            "state": {"text": "Python is required."},
                            "questions": {
                                "support": {
                                    "type": "noul",
                                    "instructions": "Is Python required?",
                                }
                            },
                        },
                    }
                ],
            },
        ).json()
        completed = client.post(f"/api/jev/runs/{created['id']}/execute-next")

        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert completed.json()["items"][0]["result"]["usage"] == {
            "input_tokens": 11,
            "output_tokens": 1,
        }
        assert "allowance" not in completed.json()
        assert received == [
            {
                "path": "/v1/systemone",
                "authorization": "Bearer test-secret",
                "body": {
                    "state": {"text": "Python is required."},
                    "model": "~typesafe/jev-latest",
                    "questions": {
                        "support": {
                            "type": "noul",
                            "instructions": "Is Python required?",
                        }
                    },
                },
            }
        ]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        engine.dispose()


def test_execute_next_is_an_explicit_manual_action(monkeypatch) -> None:
    engine, client = _client()

    class FakeEvaluator:
        async def evaluate(self, _request):
            from app.ai.system_one import (
                NoulAnswer,
                SystemOneResult,
                SystemOneUsage,
            )

            return SystemOneResult(
                status="answered",
                model="jev-latest",
                answers={"support": NoulAnswer(type="noul", noul=0.94)},
                usage=SystemOneUsage(input_tokens=9, output_tokens=1),
            )

    monkeypatch.setattr(
        jev_api, "build_jev_evaluator", lambda _db, _run: FakeEvaluator()
    )
    try:
        created = client.post(
            "/api/jev/runs",
            json={
                "purpose": "skill_evidence_evaluation",
                "rubric_version": "skill-evidence-v1",
                "items": [
                    {
                        "subject_id": "job-2:python",
                        "payload": {
                            "state": "Python required",
                            "questions": {"support": {"type": "noul"}},
                        },
                    }
                ],
            },
        ).json()

        executed = client.post(f"/api/jev/runs/{created['id']}/execute-next")
        assert executed.status_code == 200
        body = executed.json()
        assert body["status"] == "completed"
        assert body["completed_items"] == 1
        assert body["items"][0]["result"]["answers"]["support"]["noul"] == 0.94
        assert "allowance" not in body
    finally:
        engine.dispose()
