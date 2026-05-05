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
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
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


def _create_run_with_items(db, *, jobs, item_statuses, created_at, run_status):
    run = EnrichmentRun(
        source_type="manual_pending",
        status=run_status,
        job_ids=[str(job.id) for job in jobs],
        total_items=len(jobs),
        pending_items=sum(1 for status in item_statuses if status == "pending"),
        completed_items=sum(1 for status in item_statuses if status == "completed"),
        failed_items=sum(1 for status in item_statuses if status == "failed"),
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
    )
    db.add(run)
    db.flush()

    for position, (job, status) in enumerate(zip(jobs, item_statuses)):
        db.add(
            EnrichmentRunItem(
                run_id=run.id,
                job_id=job.id,
                position=position,
                status=status,
                created_at=created_at,
                started_at=created_at,
                completed_at=created_at,
                error_message=f"{status} {job.id}" if status == "failed" else None,
            )
        )

    db.commit()


@pytest.mark.asyncio
async def test_get_ai_overview_returns_failed_jobs_metric():
    client, Session = _build_test_client()
    try:
        db = Session()
        try:
            counted_job = _create_job(
                db,
                title="Counted Failed Job",
                created_at=datetime(2026, 5, 5, 9, 0, 0),
            )
            retrying_job = _create_job(
                db,
                title="Retrying Job",
                created_at=datetime(2026, 5, 5, 9, 5, 0),
            )

            _create_run_with_items(
                db,
                jobs=[counted_job],
                item_statuses=["failed"],
                created_at=datetime(2026, 5, 5, 10, 0, 0),
                run_status="failed",
            )
            _create_run_with_items(
                db,
                jobs=[counted_job],
                item_statuses=["failed"],
                created_at=datetime(2026, 5, 5, 10, 10, 0),
                run_status="failed",
            )
            _create_run_with_items(
                db,
                jobs=[retrying_job],
                item_statuses=["failed"],
                created_at=datetime(2026, 5, 5, 10, 20, 0),
                run_status="failed",
            )
            _create_run_with_items(
                db,
                jobs=[retrying_job],
                item_statuses=["pending"],
                created_at=datetime(2026, 5, 5, 10, 30, 0),
                run_status="pending",
            )
        finally:
            db.close()

        response = await client.get("/api/v1/ai/overview")

        assert response.status_code == 200
        payload = response.json()
        assert payload["failed_jobs"] == 1
        assert payload["failed_items"] == 3
    finally:
        await client.aclose()
