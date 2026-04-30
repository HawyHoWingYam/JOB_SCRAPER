import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.services.enrichment_run_service import EnrichmentRunService


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Job.__table__, EnrichmentRun.__table__, EnrichmentRunItem.__table__],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_job(
    db,
    *,
    source_classification_id,
    created_at,
    is_deleted=False,
    ai_enriched_at=None,
):
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        company_id=uuid.uuid4(),
        title="Test Job",
        description="Test Description",
        source_classification_id=source_classification_id,
        source_classification_name="Information & Communication Technology"
        if source_classification_id
        else None,
        is_deleted=is_deleted,
        ai_enriched_at=ai_enriched_at,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


def test_create_manual_pending_run_skips_jobs_missing_source_classification():
    db = _build_sqlite_session()
    try:
        expected_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 4, 30, 1, 0, 0),
        )
        _create_job(
            db,
            source_classification_id="",
            created_at=datetime(2026, 4, 30, 0, 0, 0),
        )
        _create_job(
            db,
            source_classification_id=None,
            created_at=datetime(2026, 4, 30, 2, 0, 0),
        )

        run = EnrichmentRunService(db).create_manual_pending_run(limit=10)

        assert run is not None
        assert run.total_items == 1
        assert run.job_ids == [str(expected_job.id)]
    finally:
        db.close()
