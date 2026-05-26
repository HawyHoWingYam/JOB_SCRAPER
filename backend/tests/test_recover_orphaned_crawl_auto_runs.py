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


def _create_job(db) -> Job:
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="ctgoodjobs",
        company_id=uuid.uuid4(),
        title="Pending Auto Job",
        description="Test Description",
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Information Technology",
        created_at=datetime(2026, 5, 26, 5, 0, 0),
        updated_at=datetime(2026, 5, 26, 5, 0, 0),
    )
    db.add(job)
    db.flush()
    return job


def test_cancel_orphaned_crawl_auto_runs_clears_active_pending_state_without_failed_items():
    from scripts.recover_orphaned_crawl_auto_runs import recover_orphaned_crawl_auto_runs

    db = _build_sqlite_session()
    try:
        crawl_job = CrawlJob(
            id=uuid.uuid4(),
            source_site="ctgoodjobs",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "listing"},
            metrics={"items_emitted": 2, "ingest_items_seen": 1, "ingest_items_failed": 1},
        )
        job = _create_job(db)
        db.add(crawl_job)
        db.flush()

        run = EnrichmentRun(
            source_type="crawl_auto",
            trigger_crawl_job_id=crawl_job.id,
            status="pending",
            job_ids=[str(job.id)],
            total_items=1,
            pending_items=1,
            completed_items=0,
            failed_items=0,
            created_at=datetime(2026, 5, 26, 5, 30, 0),
        )
        db.add(run)
        db.flush()
        db.add(
            EnrichmentRunItem(
                run_id=run.id,
                job_id=job.id,
                position=0,
                status="pending",
            )
        )
        db.commit()

        summary = recover_orphaned_crawl_auto_runs(db, action="cancel", limit=10)

        assert summary["selected_count"] == 1
        assert summary["cancelled_count"] == 1
        assert summary["requested_count"] == 0

        db.refresh(run)
        assert run.status == "cancelled"
        assert run.pending_items == 0
        assert run.completed_items == 0
        assert run.failed_items == 0
        assert "stale crawl_auto run cancelled" in run.error_message

        item = db.query(EnrichmentRunItem).one()
        assert item.status == "cancelled"
        assert item.error_message == run.error_message
        assert db.query(EventOutbox).count() == 0
    finally:
        db.close()
