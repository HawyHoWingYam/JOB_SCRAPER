from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job
from app.repositories.company_repository import CompanyRepository
from app.repositories.job_repository import JobRepository
from app.services.source_identity_backfill_service import SourceIdentityBackfillService


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
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def test_source_aware_upserts_create_skip_and_update_without_duplicate_rows():
    db = _build_sqlite_session()
    try:
        company_repo = CompanyRepository()
        job_repo = JobRepository()

        company_data = {
            "source_site": "jobsdb",
            "source_company_id": "61347806",
            "company_id": "61347806",
            "name": "ACME Ltd",
            "industry": "Insurance",
            "location": "Hong Kong",
            "extra_data": {"logo_url": "https://cdn.example.test/acme.png"},
        }

        company, company_action = company_repo.upsert_company(db, company_data)
        assert company_action == "created"

        same_company, company_action = company_repo.upsert_company(db, dict(company_data))
        assert company_action == "skipped"
        assert same_company.id == company.id

        updated_company, company_action = company_repo.upsert_company(
            db,
            {
                **company_data,
                "industry": "Technology",
            },
        )
        assert company_action == "updated"
        assert updated_company.id == company.id
        assert updated_company.source_site == "jobsdb"
        assert updated_company.source_company_id == "61347806"

        job_data = {
            "job_id": "91890673",
            "source_site": "jobsdb",
            "source_job_id": "91890673",
            "company_id": company.id,
            "title": "Senior Data Analyst",
            "description": "Build reporting pipelines",
            "salary_range": "HK$30,000 - HK$40,000",
            "salary_min": 30000,
            "salary_max": 40000,
            "salary_currency": "HKD",
            "location": "Hong Kong",
            "employment_type": "Full-time",
            "source_classification_id": "6281",
            "source_classification_name": "Information & Communication Technology",
            "source_subclassification_id": "6282",
            "source_subclassification_name": "Data Science",
            "raw_data": {
                "jobsdb_id": "91890673",
                "advertiser_id": "61347806",
            },
        }

        job, job_action = job_repo.upsert_source_job(db, job_data)
        assert job_action == "created"

        same_job, job_action = job_repo.upsert_source_job(db, dict(job_data))
        assert job_action == "skipped"
        assert same_job.id == job.id

        updated_job, job_action = job_repo.upsert_source_job(
            db,
            {
                **job_data,
                "salary_range": "HK$35,000 - HK$45,000",
                "salary_min": 35000,
                "salary_max": 45000,
                "raw_data": {
                    "jobsdb_id": "91890673",
                    "advertiser_id": "61347806",
                    "refresh_token": "2026-05-06T12:00:00Z",
                },
            },
        )
        assert job_action == "updated"
        assert updated_job.id == job.id

        stored_jobs = db.query(Job).all()
        assert len(stored_jobs) == 1
        assert stored_jobs[0].source_job_id == "91890673"
        assert stored_jobs[0].job_id == "91890673"
        assert stored_jobs[0].salary_range == "HK$35,000 - HK$45,000"
        assert stored_jobs[0].raw_data["refresh_token"] == "2026-05-06T12:00:00Z"
    finally:
        db.close()


def test_source_identity_backfill_splits_mixed_source_company_rows_and_repoints_jobs():
    db = _build_sqlite_session()
    try:
        root_company = Company(
            id=uuid.uuid4(),
            company_id="60190389",
            name="The Kowloon Dairy Ltd",
            industry="Food & Beverage",
            location="Hong Kong",
        )
        db.add(root_company)
        db.flush()

        jobsdb_job = Job(
            id=uuid.uuid4(),
            job_id="91890673",
            source_site="jobsdb",
            company_id=root_company.id,
            title="Senior Data Analyst",
            description="Build reports",
            raw_data={
                "jobsdb_id": "91890673",
                "advertiser_id": "60190389",
                "advertiser_name": "The Kowloon Dairy Ltd",
            },
        )
        ct_job = Job(
            id=uuid.uuid4(),
            job_id="ctgoodjobs:10090657",
            source_site="ctgoodjobs",
            company_id=root_company.id,
            title="Platform Engineer",
            description="Run ETL",
            raw_data={
                "job_id": "ctgoodjobs:10090657",
                "company_id": "00076540",
                "company_name": "The Kowloon Dairy Ltd",
            },
        )
        db.add_all([jobsdb_job, ct_job])
        db.commit()

        backfill = SourceIdentityBackfillService()
        backfill.backfill_source_identity(db)
        db.commit()

        companies = (
            db.query(Company)
            .order_by(Company.source_site.asc(), Company.source_company_id.asc())
            .all()
        )
        assert len(companies) == 2

        jobsdb_company = (
            db.query(Company)
            .filter(
                Company.source_site == "jobsdb",
                Company.source_company_id == "60190389",
            )
            .one()
        )
        ct_company = (
            db.query(Company)
            .filter(
                Company.source_site == "ctgoodjobs",
                Company.source_company_id == "00076540",
            )
            .one()
        )

        db.refresh(jobsdb_job)
        db.refresh(ct_job)

        assert jobsdb_company.id == root_company.id
        assert jobsdb_company.company_id == "60190389"
        assert ct_company.company_id == "ctgoodjobs:00076540"
        assert jobsdb_job.company_id == jobsdb_company.id
        assert ct_job.company_id == ct_company.id
        assert jobsdb_job.source_job_id == "91890673"
        assert ct_job.source_job_id == "10090657"
    finally:
        db.close()


def test_source_identity_backfill_reuses_existing_source_owned_company_rows():
    db = _build_sqlite_session()
    try:
        root_company = Company(
            id=uuid.uuid4(),
            company_id="61316610",
            name="Global Virtual Design And Construction Limited",
            industry="Information & Communication Technology",
            location="Hong Kong SAR",
        )
        existing_ct_company = Company(
            id=uuid.uuid4(),
            company_id="ctgoodjobs:00015403",
            name="Global Virtual Design And Construction Limited",
            industry="Information & Communication Technology",
            location="Hong Kong SAR",
        )
        db.add_all([root_company, existing_ct_company])
        db.flush()

        jobsdb_job = Job(
            id=uuid.uuid4(),
            job_id="91904115",
            source_site="jobsdb",
            company_id=root_company.id,
            title="BIM Engineer",
            description="Build digital twins",
            raw_data={
                "jobsdb_id": "91904115",
                "advertiser_id": "61316610",
                "advertiser_name": "Global Virtual Design And Construction Limited",
            },
        )
        ct_job = Job(
            id=uuid.uuid4(),
            job_id="ctgoodjobs:10090658",
            source_site="ctgoodjobs",
            company_id=root_company.id,
            title="VDC Manager",
            description="Own BIM delivery",
            raw_data={
                "job_id": "ctgoodjobs:10090658",
                "company_id": "00015403",
                "company_name": "Global Virtual Design And Construction Limited",
            },
        )
        db.add_all([jobsdb_job, ct_job])
        db.commit()

        backfill = SourceIdentityBackfillService()
        backfill.backfill_source_identity(db)
        db.commit()

        companies = db.query(Company).order_by(Company.company_id.asc()).all()
        assert [company.company_id for company in companies] == [
            "61316610",
            "ctgoodjobs:00015403",
        ]

        db.refresh(ct_job)
        assert ct_job.company_id == existing_ct_company.id
    finally:
        db.close()
