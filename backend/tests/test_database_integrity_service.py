from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import (
    Company,
    CrawlJob,
    CrawlJobListing,
    EventOutbox,
    Job,
    JobCategory,
    JobDomain,
    JobEmbedding,
    JobSubcategory,
    ScheduleExecution,
    ScrapeSchedule,
    Skill,
    SkillCategory,
    SkillTechnology,
)
from app.models.job_embedding import EMBEDDING_DIMENSIONS
from app.services.database_integrity_service import build_database_integrity_summary

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session_factory(*, tables=None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=tables
        or [
            Company.__table__,
            Job.__table__,
            CrawlJob.__table__,
            CrawlJobListing.__table__,
            EventOutbox.__table__,
            JobEmbedding.__table__,
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _create_company(db) -> Company:
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        source_site="jobsdb",
        source_company_id=f"source-company-{uuid.uuid4()}",
        name="Acme",
    )
    db.add(company)
    db.flush()
    return company


def _create_job(db, company: Company, *, title: str = "Engineer") -> Job:
    job = Job(
        id=uuid.uuid4(),
        job_id=f"jobsdb:{uuid.uuid4()}",
        source_site="jobsdb",
        source_job_id=f"source-job-{uuid.uuid4()}",
        company_id=company.id,
        title=title,
        is_deleted=False,
    )
    db.add(job)
    db.flush()
    return job


def _create_crawl_job(db) -> CrawlJob:
    crawl_job = CrawlJob(
        id=uuid.uuid4(),
        source_site="jobsdb",
        trigger_type="manual",
        status="completed",
        request_payload={"source_site": "jobsdb"},
        requested_by="pytest",
    )
    db.add(crawl_job)
    db.flush()
    return crawl_job


def _create_listing(db, crawl_job: CrawlJob, *, source_job_id: str, published_job_id=None) -> CrawlJobListing:
    row = CrawlJobListing(
        id=uuid.uuid4(),
        crawl_job_id=crawl_job.id,
        source_site="jobsdb",
        source_job_id=source_job_id,
        source_url=f"https://hk.jobsdb.com/job/{source_job_id}",
        source_classification_id="6281",
        source_classification_name="ICT",
        listing_page=1,
        listing_rank=1,
        listing_payload={"title": source_job_id},
        detail_status="completed" if published_job_id else "pending",
        published_job_id=published_job_id,
    )
    db.add(row)
    db.flush()
    return row


def _expected_tables() -> list[str]:
    return [
        "companies",
        "jobs",
        "crawl_jobs",
        "crawl_job_listings",
        "event_outbox",
        "job_embeddings",
        "scrape_schedules",
        "schedule_executions",
        "job_domains",
        "job_categories",
        "job_subcategories",
        "skill_categories",
        "skill_technologies",
        "skills",
    ]


def test_staging_ratios_count_unpublished_rows():
    Session = _build_sqlite_session_factory()
    db = Session()
    try:
        company = _create_company(db)
        first_job = _create_job(db, company, title="Platform Engineer")
        second_job = _create_job(db, company, title="Data Engineer")
        crawl_job = _create_crawl_job(db)
        _create_listing(db, crawl_job, source_job_id="1001", published_job_id=first_job.id)
        _create_listing(db, crawl_job, source_job_id="1002", published_job_id=second_job.id)
        for source_job_id in ("1003", "1004", "1005"):
            _create_listing(db, crawl_job, source_job_id=source_job_id)
        db.commit()

        summary = build_database_integrity_summary(
            session_factory=Session,
            expected_tables=_expected_tables(),
        )

        assert summary["staging"] == {
            "total_staged_rows": 5,
            "staged_published_rows": 2,
            "staged_unpublished_rows": 3,
            "published_jobs": 2,
            "staged_to_published_ratio": 2.5,
        }
    finally:
        db.close()


def test_outbox_retry_and_oldest_pending_age_metrics():
    Session = _build_sqlite_session_factory()
    db = Session()
    reference_time = datetime(2026, 5, 22, 8, 0, 0, tzinfo=timezone.utc)
    try:
        db.add_all(
            [
                EventOutbox(
                    topic="stream.job.ingest",
                    aggregate_type="job",
                    aggregate_id="1",
                    event_type="job.created",
                    source_service="pytest",
                    payload={},
                    status="pending",
                    attempt_count=2,
                    available_at=reference_time - timedelta(seconds=120),
                    created_at=reference_time - timedelta(seconds=120),
                ),
                EventOutbox(
                    topic="stream.job.ingest",
                    aggregate_type="job",
                    aggregate_id="2",
                    event_type="job.created",
                    source_service="pytest",
                    payload={},
                    status="pending",
                    attempt_count=0,
                    available_at=reference_time - timedelta(seconds=30),
                    created_at=reference_time - timedelta(seconds=30),
                ),
                EventOutbox(
                    topic="stream.job.ingest",
                    aggregate_type="job",
                    aggregate_id="3",
                    event_type="job.created",
                    source_service="pytest",
                    payload={},
                    status="published",
                    attempt_count=1,
                    available_at=reference_time - timedelta(seconds=300),
                    created_at=reference_time - timedelta(seconds=300),
                    published_at=reference_time - timedelta(seconds=240),
                ),
            ]
        )
        db.commit()

        summary = build_database_integrity_summary(
            session_factory=Session,
            expected_tables=_expected_tables(),
            reference_time=reference_time,
        )

        assert summary["outbox"]["status_counts"] == {"pending": 2, "published": 1}
        assert summary["outbox"]["retrying_rows"] == 1
        assert summary["outbox"]["max_attempts"] == 2
        assert summary["outbox"]["oldest_pending_age_seconds"] == 120
    finally:
        db.close()


def test_taxonomy_empty_state_detection():
    Session = _build_sqlite_session_factory()

    summary = build_database_integrity_summary(
        session_factory=Session,
        expected_tables=_expected_tables(),
    )

    assert summary["taxonomy"]["all_seed_tables_empty"] is True
    assert summary["taxonomy"]["empty_seed_tables"] == [
        "job_domains",
        "job_categories",
        "job_subcategories",
        "skill_categories",
        "skill_technologies",
        "skills",
    ]


def test_advisory_missing_fk_and_vector_index_findings_do_not_make_status_critical():
    Session = _build_sqlite_session_factory()
    db = Session()
    try:
        job_domain = JobDomain(id=uuid.uuid4(), name="Information Technology")
        job_category = JobCategory(id=uuid.uuid4(), domain=job_domain, name="Software")
        job_subcategory = JobSubcategory(id=uuid.uuid4(), category=job_category, name="Backend")
        skill_category = SkillCategory(id=uuid.uuid4(), name="Engineering")
        skill_technology = SkillTechnology(id=uuid.uuid4(), category=skill_category, name="Python")
        skill = Skill(id=uuid.uuid4(), technology=skill_technology, name="FastAPI", aliases=None)
        db.add_all([job_domain, job_category, job_subcategory, skill_category, skill_technology, skill])
        db.commit()

        summary = build_database_integrity_summary(
            session_factory=Session,
            expected_tables=_expected_tables(),
        )

        finding_ids = {finding["id"] for finding in summary["advisory_findings"]}
        assert "crawl_job_listings_crawl_job_id_fk" in finding_ids
        assert "job_embeddings_embedding_ann_index" in finding_ids
        assert summary["status"] == "healthy"
    finally:
        db.close()


def test_missing_expected_tables_make_status_critical():
    Session = _build_sqlite_session_factory(tables=[Company.__table__])

    summary = build_database_integrity_summary(
        session_factory=Session,
        expected_tables=["companies", "jobs"],
    )

    assert summary["status"] == "critical"
    assert summary["schema"]["missing_expected_tables"] == ["jobs"]
    assert "missing expected database tables: jobs" in summary["issues"]
