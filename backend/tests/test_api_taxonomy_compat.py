import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import jobs as jobs_api
from app.api import stats as stats_api
from app.database import Base
from app.models import Company, Job, JobCategory, JobDomain, JobSubcategory
from app.schemas.job_search import (
    JobSearchFiltersSchema,
    JobSearchLayerSchema,
    JobSearchScopeSchema,
)

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"


CANONICAL_PATH = (
    "Information & Communication Technology / "
    "Software Development / Backend Development"
)
LEGACY_ONLY_PATH = "Sales / Field Sales / Account Executive"


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            Job.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id="company-1",
        name="Acme",
        industry="Technology",
    )
    db.add(company)
    db.commit()
    return company


def _seed_taxonomy(db):
    domain = JobDomain(
        id=uuid.uuid4(),
        name="Information & Communication Technology",
    )
    category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="Software Development",
    )
    subcategory = JobSubcategory(
        id=uuid.uuid4(),
        category_id=category.id,
        name="Backend Development",
    )
    db.add_all([domain, category, subcategory])
    db.commit()
    return subcategory


def _seed_job(
    db,
    *,
    company_id,
    job_id,
    title,
    ai_category,
    subcategory_id=None,
):
    job = Job(
        id=uuid.uuid4(),
        job_id=job_id,
        company_id=company_id,
        title=title,
        ai_category=ai_category,
        subcategory_id=subcategory_id,
        is_deleted=False,
    )
    db.add(job)
    db.commit()
    return job


def test_legacy_category_filter_matches_canonical_taxonomy_path():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        backend = _seed_taxonomy(db)

        canonical_job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical",
            title="Backend Engineer",
            ai_category="Legacy backend text that should not matter",
            subcategory_id=backend.id,
        )
        legacy_job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-legacy",
            title="Account Executive",
            ai_category=LEGACY_ONLY_PATH,
        )

        query = db.query(Job, Company).join(Company, Job.company_id == Company.id)
        query = query.filter(Job.is_deleted.is_(False))
        query = jobs_api._apply_structured_filters(
            query,
            JobSearchFiltersSchema(category=CANONICAL_PATH),
        )
        results = query.order_by(Job.job_id.asc()).all()

        assert [(job.job_id, company.name) for job, company in results] == [
            (canonical_job.job_id, "Acme"),
        ]
        assert legacy_job.job_id not in [job.job_id for job, _ in results]
    finally:
        db.close()


def test_category_stats_group_by_canonical_taxonomy_path_with_legacy_fallback():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        backend = _seed_taxonomy(db)

        _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical-1",
            title="Backend Engineer",
            ai_category="Outdated backend label",
            subcategory_id=backend.id,
        )
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical-2",
            title="Platform Engineer",
            ai_category=None,
            subcategory_id=backend.id,
        )
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-legacy",
            title="Account Executive",
            ai_category=LEGACY_ONLY_PATH,
        )

        results = asyncio.run(stats_api.get_category_stats(db=db))

        assert results == [
            {"category": CANONICAL_PATH, "count": 2},
            {"category": LEGACY_ONLY_PATH, "count": 1},
        ]
    finally:
        db.close()
