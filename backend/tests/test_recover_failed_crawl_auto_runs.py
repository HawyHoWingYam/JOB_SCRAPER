import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models.crawl_job import CrawlJob
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job import Job

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
            EventOutbox.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_job(db, *, title: str) -> Job:
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        company_id=uuid.uuid4(),
        title=title,
        description="Test Description",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        created_at=datetime(2026, 5, 21, 8, 0, 0),
        updated_at=datetime(2026, 5, 21, 8, 0, 0),
    )
    db.add(job)
    db.flush()
    return job


def test_recover_failed_crawl_auto_runs_creates_retry_run_and_execution_request():
    from scripts.recover_failed_crawl_auto_runs import recover_failed_crawl_auto_runs

    db = _build_sqlite_session()
    try:
        crawl_job = CrawlJob(
            id=uuid.uuid4(),
            source_site="jobsdb",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "listing"},
            metrics={"items_emitted": 2, "ingest_items_seen": 2},
        )
        completed_job = _create_job(db, title="Completed Job")
        failed_job = _create_job(db, title="Failed Job")
        db.add(crawl_job)
        db.flush()

        failed_run = EnrichmentRun(
            source_type="crawl_auto",
            trigger_crawl_job_id=crawl_job.id,
            status="failed",
            job_ids=[str(completed_job.id), str(failed_job.id)],
            total_items=2,
            pending_items=0,
            completed_items=1,
            failed_items=1,
            error_message="worker exited",
        )
        db.add(failed_run)
        db.flush()
        db.add(
            EnrichmentRunItem(
                run_id=failed_run.id,
                job_id=completed_job.id,
                position=0,
                status="completed",
            )
        )
        db.add(
            EnrichmentRunItem(
                run_id=failed_run.id,
                job_id=failed_job.id,
                position=1,
                status="failed",
                error_message="timeout",
            )
        )
        db.commit()

        summary = recover_failed_crawl_auto_runs(db, limit=10, execute=True)

        assert summary["selected_count"] == 1
        assert summary["created_count"] == 1
        assert summary["requested_count"] == 1
        assert summary["skipped_count"] == 0

        retry_run = (
            db.query(EnrichmentRun)
            .filter(EnrichmentRun.source_type == "retry_failed")
            .one()
        )
        assert retry_run.job_ids == [str(failed_job.id)]
        assert retry_run.pending_items == 1

        outbox = db.query(EventOutbox).one()
        assert outbox.event_type == "enrichment.run.requested"
        assert outbox.aggregate_id == retry_run.id
        assert outbox.source_service == "enrichment-recovery"
    finally:
        db.close()
