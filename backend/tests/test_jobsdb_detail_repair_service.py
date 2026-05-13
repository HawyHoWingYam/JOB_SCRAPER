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
from app.models import Company, Job
from app.services.jobsdb_detail_repair_service import JobsDBDetailRepairService


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


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


def _create_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id="company-1",
        source_site="jobsdb",
        source_company_id="adv-1",
        name="ACME Ltd",
    )
    db.add(company)
    db.commit()
    return company


def test_jobsdb_detail_repair_service_lists_degraded_jobs_only():
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        degraded = Job(
            id=uuid.uuid4(),
            job_id="92065180",
            source_site="jobsdb",
            source_job_id="92065180",
            company_id=company.id,
            title="Short Description Job",
            description="Conduct a security risk assessment",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name=None,
            raw_data={"external_id": "92065180", "teaser": "Conduct a security risk assessment"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        healthy = Job(
            id=uuid.uuid4(),
            job_id="92000001",
            source_site="jobsdb",
            source_job_id="92000001",
            company_id=company.id,
            title="Healthy Detail Job",
            description="X" * 600,
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name="Security",
            raw_data={"jobsdb_id": "92000001", "description_html": "<p>Long</p>"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        other_source = Job(
            id=uuid.uuid4(),
            job_id="ctgoodjobs:1001",
            source_site="ctgoodjobs",
            source_job_id="1001",
            company_id=company.id,
            title="CT Job",
            description="short",
            raw_data={"job_id": "1001"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add_all([degraded, healthy, other_source])
        db.commit()

        service = JobsDBDetailRepairService(db)
        candidates = service.iter_repair_candidates(limit=10)

        assert [job.source_job_id for job in candidates] == ["92065180"]
    finally:
        db.close()


def test_jobsdb_detail_repair_service_applies_detail_payload_without_changing_identity():
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        job = Job(
            id=uuid.uuid4(),
            job_id="92065180",
            source_site="jobsdb",
            source_job_id="92065180",
            company_id=company.id,
            title="Short Description Job",
            description="Conduct a security risk assessment",
            source_classification_id="6281",
            source_classification_name="Information & Communication Technology",
            source_subclassification_name=None,
            employment_type="Full time",
            raw_data={"external_id": "92065180", "teaser": "Conduct a security risk assessment"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()

        service = JobsDBDetailRepairService(db)
        service.apply_parsed_detail(
            job,
            {
                "jobsdb_id": "92065180",
                "title": "Specialist, IT Risk & Security",
                "abstract": "Conduct a security risk assessment",
                "description_html": "<p>Full detailed description</p>",
                "classification_id": "6281",
                "classification": "Information & Communication Technology",
                "subclassification_id": "6310",
                "subclassification": "Security",
                "location": "Airport Area, Islands District",
                "work_type": "Full-time",
                "salary": None,
                "listing_date": "2026-05-12T08:55:58+00:00",
                "expiry_date": "2026-06-12T08:55:58+00:00",
                "is_expired": False,
                "advertiser_id": "61321356",
                "advertiser_name": "Hong Kong Express Airways Limited",
                "status": "ACTIVE",
            },
        )
        db.commit()
        db.refresh(job)

        assert job.source_job_id == "92065180"
        assert job.description == "<p>Full detailed description</p>"
        assert job.source_subclassification_id == "6310"
        assert job.source_subclassification_name == "Security"
        assert job.raw_data["jobsdb_id"] == "92065180"
        assert job.raw_data["description_html"] == "<p>Full detailed description</p>"
        assert job.raw_data["teaser"] == "Conduct a security risk assessment"
    finally:
        db.close()
