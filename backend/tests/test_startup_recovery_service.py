import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models.company import Company
from app.models.crawl_job import CrawlJob
from app.models.company_enrichment_run import CompanyEnrichmentRun, CompanyEnrichmentRunItem
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.models.schedule import ScrapeSchedule, ScheduleExecution
from app.services.startup_recovery_service import StartupRecoveryService


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
            Company.__table__,
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
            CompanyEnrichmentRun.__table__,
            CompanyEnrichmentRunItem.__table__,
            CrawlJob.__table__,
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_company(db, *, name: str) -> Company:
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{name.lower().replace(' ', '-')}",
        name=name,
        industry="Technology",
        location="Hong Kong",
        created_at=datetime(2026, 5, 5, 9, 0, 0),
        updated_at=datetime(2026, 5, 5, 9, 0, 0),
    )
    db.add(company)
    db.commit()
    return company


def _create_job(db, *, company_id: uuid.UUID, title: str) -> Job:
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        company_id=company_id,
        title=title,
        description="Test Description",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        created_at=datetime(2026, 5, 5, 9, 30, 0),
        updated_at=datetime(2026, 5, 5, 9, 30, 0),
    )
    db.add(job)
    db.commit()
    return job


def test_recover_interrupted_operations_marks_active_runs_and_executions_failed():
    db = _build_sqlite_session()
    try:
        service = StartupRecoveryService(db)
        call_order = []

        def record_ai():
            call_order.append("ai")
            return 2

        def record_company():
            call_order.append("company")
            return 3

        def record_schedule():
            call_order.append("schedule")
            return 4

        def record_crawl_jobs():
            call_order.append("crawl")
            return 1

        service._recover_ai_runs = record_ai
        service._recover_company_runs = record_company
        service._recover_crawl_jobs = record_crawl_jobs
        service._recover_schedule_executions = record_schedule

        summary = service.recover_interrupted_operations()

        assert call_order == ["ai", "company", "crawl", "schedule"]
        assert summary == {
            "ai_runs_recovered": 2,
            "company_runs_recovered": 3,
            "crawl_jobs_recovered": 1,
            "schedule_executions_recovered": 4,
        }
    finally:
        db.close()


def test_recover_interrupted_operations_tolerates_legacy_schedule_execution_schema():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
            CompanyEnrichmentRun.__table__,
            CompanyEnrichmentRunItem.__table__,
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE schedule_executions (
                    id CHAR(32) PRIMARY KEY,
                    schedule_id CHAR(32) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    started_at DATETIME NOT NULL,
                    completed_at DATETIME,
                    duration_seconds INTEGER,
                    jobs_scraped INTEGER DEFAULT 0,
                    jobs_saved INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at DATETIME
                )
                """
            )
        )
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        legacy_execution_id = uuid.uuid4().hex
        db.execute(
            text(
                """
                INSERT INTO schedule_executions (
                    id, schedule_id, status, started_at, completed_at, duration_seconds,
                    jobs_scraped, jobs_saved, error_message, created_at
                ) VALUES (
                    :id, :schedule_id, :status, :started_at, :completed_at, :duration_seconds,
                    :jobs_scraped, :jobs_saved, :error_message, :created_at
                )
                """
            ),
            {
                "id": legacy_execution_id,
                "schedule_id": uuid.uuid4().hex,
                "status": "running",
                "started_at": datetime(2026, 5, 5, 11, 10, 0),
                "completed_at": None,
                "duration_seconds": None,
                "jobs_scraped": 5,
                "jobs_saved": 5,
                "error_message": None,
                "created_at": datetime(2026, 5, 5, 11, 10, 0),
            },
        )
        db.commit()

        schedule_count = StartupRecoveryService(db)._recover_schedule_executions()
        db.commit()

        legacy_execution = db.execute(
            text("SELECT status, error_message, completed_at FROM schedule_executions WHERE id = :id"),
            {"id": legacy_execution_id},
        ).mappings().one()

        assert schedule_count == 1
        assert legacy_execution["status"] == "failed"
        assert "service restarted" in legacy_execution["error_message"].lower()
        assert legacy_execution["completed_at"] is not None
    finally:
        db.close()


def test_recover_interrupted_operations_keeps_ai_and_company_results_when_schedule_recovery_fails():
    db = _build_sqlite_session()
    try:
        service = StartupRecoveryService(db)

        service._recover_ai_runs = lambda: 1
        service._recover_company_runs = lambda: 2
        service._recover_crawl_jobs = lambda: 3

        def fail_schedule():
            raise RuntimeError("legacy schedule schema mismatch")

        service._recover_schedule_executions = fail_schedule

        summary = service.recover_interrupted_operations()

        assert summary == {
            "ai_runs_recovered": 1,
            "company_runs_recovered": 2,
            "crawl_jobs_recovered": 3,
            "schedule_executions_recovered": 0,
        }
    finally:
        db.close()


def test_recover_crawl_jobs_marks_running_jobs_failed():
    db = _build_sqlite_session()
    try:
        crawl_job = CrawlJob(
            source_site="jobsdb",
            trigger_type="manual",
            status="running",
            request_payload={"category_ids": [1200], "max_pages": 3},
            requested_by="pytest",
        )
        db.add(crawl_job)
        db.commit()

        recovered = StartupRecoveryService(db)._recover_crawl_jobs()
        db.commit()
        db.refresh(crawl_job)

        assert recovered == 1
        assert crawl_job.status == "failed"
        assert crawl_job.completed_at is not None
        assert "restarted" in (crawl_job.error_message or "").lower()
    finally:
        db.close()
