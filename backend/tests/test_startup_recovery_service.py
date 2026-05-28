from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.services.startup_recovery_service import AI_RESTART_MESSAGE, StartupRecoveryService


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()

    company = Company(
        company_id="company-1",
        source_site="jobsdb",
        source_company_id="company-1",
        name="Example Co",
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    job = Job(
        job_id="job-1",
        source_site="jobsdb",
        source_job_id="job-1",
        company_id=company.id,
        title="Job 1",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return db, job


def test_recover_ai_runs_only_skips_queued_pending_runs_that_never_started():
    db, job = _build_session()
    run = EnrichmentRun(
        id="queued-run",
        source_type="manual_pending",
        status="pending",
        job_ids=[str(job.id)],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        started_at=None,
        completed_at=None,
    )
    db.add(run)
    db.add(
        EnrichmentRunItem(
            id="queued-item",
            run_id=run.id,
            job_id=job.id,
            position=0,
            status="pending",
            created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    recovered = StartupRecoveryService(db).recover_ai_runs_only()
    db.refresh(run)

    assert recovered == 0
    assert run.status == "pending"
    assert run.completed_at is None
    assert run.error_message is None
    db.close()


def test_recover_ai_runs_only_marks_started_runs_failed_after_restart():
    db, job = _build_session()
    run = EnrichmentRun(
        id="running-run",
        source_type="manual_pending",
        status="running",
        job_ids=[str(job.id)],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        started_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
        completed_at=None,
    )
    db.add(run)
    db.add(
        EnrichmentRunItem(
            id="running-item",
            run_id=run.id,
            job_id=job.id,
            position=0,
            status="running",
            started_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
            created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()

    recovered = StartupRecoveryService(db).recover_ai_runs_only()
    db.refresh(run)
    item = db.query(EnrichmentRunItem).filter(EnrichmentRunItem.run_id == run.id).one()

    assert recovered == 1
    assert run.status == "failed"
    assert run.pending_items == 0
    assert run.failed_items == 1
    assert run.completed_at is not None
    assert run.error_message == AI_RESTART_MESSAGE
    assert item.status == "failed"
    assert item.error_message == AI_RESTART_MESSAGE
    db.close()
