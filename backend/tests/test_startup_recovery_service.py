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
from app.models.company import Company
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
        company = _create_company(db, name="Acme Health")
        job = _create_job(db, company_id=company.id, title="Platform Engineer")

        ai_run = EnrichmentRun(
            id="ai-run-1",
            source_type="manual_pending",
            status="running",
            job_ids=[str(job.id)],
            total_items=1,
            pending_items=0,
            completed_items=0,
            failed_items=0,
            started_at=datetime(2026, 5, 5, 10, 0, 0),
            current_job_title="Platform Engineer",
            created_at=datetime(2026, 5, 5, 10, 0, 0),
        )
        db.add(ai_run)
        db.flush()
        db.add(
            EnrichmentRunItem(
                id="ai-item-1",
                run_id=ai_run.id,
                job_id=job.id,
                position=0,
                status="running",
                started_at=datetime(2026, 5, 5, 10, 0, 5),
                created_at=datetime(2026, 5, 5, 10, 0, 0),
            )
        )

        company_run = CompanyEnrichmentRun(
            id="company-run-1",
            status="pending",
            total_items=1,
            pending_items=1,
            completed_items=0,
            failed_items=0,
            started_at=datetime(2026, 5, 5, 10, 5, 0),
            current_company_name="Acme Health",
            created_at=datetime(2026, 5, 5, 10, 5, 0),
        )
        db.add(company_run)
        db.flush()
        db.add(
            CompanyEnrichmentRunItem(
                id="company-item-1",
                run_id=company_run.id,
                company_id=company.id,
                position=0,
                status="pending",
                created_at=datetime(2026, 5, 5, 10, 5, 0),
            )
        )

        schedule = ScrapeSchedule(
            id=uuid.uuid4(),
            name="Nightly Import",
            cron_expression="0 2 * * *",
            source_site="jobsdb",
            category_ids=[1200],
            created_at=datetime(2026, 5, 5, 8, 0, 0),
            updated_at=datetime(2026, 5, 5, 8, 0, 0),
        )
        db.add(schedule)
        db.flush()
        execution = ScheduleExecution(
            schedule_id=schedule.id,
            status="ai_running",
            started_at=datetime(2026, 5, 5, 10, 10, 0),
            phase1_completed=True,
            phase2_completed=True,
            phase3_completed=True,
            phase4_completed=True,
            phase5_completed=False,
            jobs_scraped=8,
            jobs_saved=8,
            jobs_classified=4,
            created_at=datetime(2026, 5, 5, 10, 10, 0),
        )
        db.add(execution)
        db.commit()

        summary = StartupRecoveryService(db).recover_interrupted_operations()

        db.expire_all()
        recovered_ai_run = db.query(EnrichmentRun).filter(EnrichmentRun.id == ai_run.id).one()
        recovered_ai_item = db.query(EnrichmentRunItem).filter(EnrichmentRunItem.id == "ai-item-1").one()
        recovered_company_run = db.query(CompanyEnrichmentRun).filter(CompanyEnrichmentRun.id == company_run.id).one()
        recovered_company_item = db.query(CompanyEnrichmentRunItem).filter(
            CompanyEnrichmentRunItem.id == "company-item-1"
        ).one()
        recovered_execution = db.query(ScheduleExecution).filter(ScheduleExecution.id == execution.id).one()

        assert summary == {
            "ai_runs_recovered": 1,
            "company_runs_recovered": 1,
            "schedule_executions_recovered": 1,
        }

        assert recovered_ai_run.status == "failed"
        assert recovered_ai_run.pending_items == 0
        assert recovered_ai_run.completed_items == 0
        assert recovered_ai_run.failed_items == 1
        assert recovered_ai_run.current_job_title is None
        assert recovered_ai_run.completed_at is not None
        assert "service restarted" in recovered_ai_run.error_message.lower()
        assert recovered_ai_item.status == "failed"
        assert "service restarted" in recovered_ai_item.error_message.lower()

        assert recovered_company_run.status == "failed"
        assert recovered_company_run.pending_items == 0
        assert recovered_company_run.completed_items == 0
        assert recovered_company_run.failed_items == 1
        assert recovered_company_run.current_company_name is None
        assert recovered_company_run.completed_at is not None
        assert "service restarted" in recovered_company_run.error_message.lower()
        assert recovered_company_item.status == "failed"
        assert "service restarted" in recovered_company_item.error_message.lower()

        assert recovered_execution.status == "failed"
        assert recovered_execution.completed_at is not None
        assert "service restarted" in recovered_execution.error_message.lower()
    finally:
        db.close()
