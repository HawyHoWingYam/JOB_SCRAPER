import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.ai import router as ai_router
from app.database import Base, get_db
from app.messaging.topics import STREAM_JOB_LIFECYCLE
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job import Job


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_test_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
            EventOutbox.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(ai_router)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, Session


def _create_job(db, *, title, created_at):
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        source_job_id=str(uuid.uuid4()),
        company_id=uuid.uuid4(),
        title=title,
        description="Test Description",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


@pytest.mark.asyncio
async def test_create_enrichment_run_enqueues_worker_request_instead_of_running_inline(monkeypatch):
    monkeypatch.setattr("app.api.ai.ensure_profile_runtime_ready", lambda *_args, **_kwargs: None)
    client, Session = _build_test_client()
    monkeypatch.setattr("app.api.ai.SessionLocal", Session)
    try:
        db = Session()
        try:
            _create_job(
                db,
                title="Queued Manual Run Job",
                created_at=datetime(2026, 5, 5, 16, 0, 0),
            )
        finally:
            db.close()

        response = await client.post("/api/v1/ai/runs", json={"mode": "pending"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "pending"

        db = Session()
        try:
            run = db.query(EnrichmentRun).one()
            item = db.query(EnrichmentRunItem).one()
            outbox_rows = db.query(EventOutbox).all()

            assert run.status == "pending"
            assert item.status == "pending"
            assert len(outbox_rows) == 1
            assert outbox_rows[0].topic == STREAM_JOB_LIFECYCLE
            assert outbox_rows[0].event_type == "enrichment.run.requested"
            assert outbox_rows[0].payload["run_id"] == run.id
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enrich_single_job_waits_for_worker_owned_run_and_returns_job_snapshot(monkeypatch):
    monkeypatch.setattr("app.api.ai.ensure_profile_runtime_ready", lambda *_args, **_kwargs: None)
    client, Session = _build_test_client()
    monkeypatch.setattr("app.api.ai.SessionLocal", Session)
    try:
        db = Session()
        try:
            job = _create_job(
                db,
                title="Single Worker-Owned Job",
                created_at=datetime(2026, 5, 5, 16, 30, 0),
            )
            job_id = job.id
        finally:
            db.close()

        async def fake_wait_for_terminal_run(run_id: str):
            db = Session()
            try:
                run = db.query(EnrichmentRun).filter(EnrichmentRun.id == run_id).one()
                item = db.query(EnrichmentRunItem).filter(EnrichmentRunItem.run_id == run_id).one()
                refreshed_job = db.query(Job).filter(Job.id == job_id).one()
                refreshed_job.ai_enriched_at = datetime(2026, 5, 5, 16, 45, 0)
                item.status = "completed"
                item.started_at = datetime(2026, 5, 5, 16, 40, 0)
                item.completed_at = datetime(2026, 5, 5, 16, 45, 0)
                run.status = "completed"
                run.pending_items = 0
                run.completed_items = 1
                run.failed_items = 0
                run.started_at = datetime(2026, 5, 5, 16, 40, 0)
                run.completed_at = datetime(2026, 5, 5, 16, 45, 0)
                db.commit()
                db.refresh(run)
                return run
            finally:
                db.close()

        monkeypatch.setattr("app.api.ai._wait_for_terminal_run", fake_wait_for_terminal_run)
        monkeypatch.setattr(
            "app.api.ai._load_job_snapshot",
            lambda _job_id: {
                "id": str(job_id),
                "title": "Single Worker-Owned Job",
                "ai_enriched_at": "2026-05-05T16:45:00",
            },
        )

        response = await client.post(f"/api/v1/ai/enrich-job/{job_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["run"]["status"] == "completed"
        assert payload["job"]["id"] == str(job_id)
        assert payload["job"]["ai_enriched_at"] == "2026-05-05T16:45:00"
    finally:
        await client.aclose()
